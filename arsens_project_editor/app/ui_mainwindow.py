"""PySide6 main window: toolbar, project tree, inspector, 3D viewport, data tables, validation log."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from pyvistaqt import QtInteractor

from . import excel_io, export_package, json_io, mesh_loader, validation
from . import geometry as geo
from .models import Marker, PlacementOrigin, Project, Sensor, SensorStatus, StlModel
from .viewport import TransformerScene

_ERROR_RED = "#D32F2F"
_WARN_AMBER = "#C9851F"

_STATUS_OPTS = ["pending", "ok", "fail"]
_ORIGIN_OPTS = ["prepared", "on_the_fly"]
_PLANE_OPTS = ["front", "back", "left", "right", "top"]
_ROLE_OPTS = ["TANK", "COVER", "CORE", "ACTIVE_PART", "WIKSETS", "BUSHINGS_TURRETS", "OTHER"]
_YESNO_OPTS = ["yes", "no"]
_MODEL_FILTER = "3D models (*.stl *.obj *.ply *.glb *.gltf *.3mf *.off *.dae);;All files (*)"


def _noedit(item: QtWidgets.QTableWidgetItem) -> QtWidgets.QTableWidgetItem:
    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
    return item


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ARsens Project Editor")
        self.resize(1320, 880)
        self.project = Project(project_name="New project")
        self.model_sources: dict[str, str] = {}
        self.core_bounds: dict[str, np.ndarray] = {}  # file_name -> wall box (model-space)
        self._loading = False

        self.interactor = QtInteractor(self)
        self.setCentralWidget(self.interactor)
        self.scene = TransformerScene(self.interactor)
        self.scene.set_project(self.project)

        self._build_toolbar()
        self._build_left_dock()
        self._build_right_dock()
        self._build_bottom_dock()
        self.refresh_all()

    # --- construction -----------------------------------------------------

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        def act(text, fn):
            a = QtGui.QAction(text, self)
            a.triggered.connect(fn)
            tb.addAction(a)
            return a

        act("New", self.new_project)
        act("Open", self.open_project)
        act("Save JSON", self.save_project)
        tb.addSeparator()
        act("Import 3D model", self.import_model)
        act("Import Excel", self.import_excel)
        tb.addSeparator()
        act("Export package", self.export_package)
        act("Export Excel template", self.export_excel)
        tb.addSeparator()
        act("Validate", self.validate)
        tb.addSeparator()
        for label, preset in (("Front", "front"), ("Back", "back"), ("Left", "left"),
                              ("Right", "right"), ("Top", "top"), ("Iso", "iso")):
            a = QtGui.QAction(label, self)
            a.triggered.connect(lambda _checked=False, pr=preset: self.scene.view(pr))
            tb.addAction(a)
        tb.addSeparator()
        self.pick_action = QtGui.QAction("Click-place sensor", self)
        self.pick_action.setCheckable(True)
        self.pick_action.toggled.connect(self._toggle_pick)
        tb.addAction(self.pick_action)
        self.pick_tag_action = QtGui.QAction("Click-place tag", self)
        self.pick_tag_action.setCheckable(True)
        self.pick_tag_action.toggled.connect(self._toggle_pick_tag)
        tb.addAction(self.pick_tag_action)
        tb.addSeparator()
        self.labels_action = QtGui.QAction("Labels", self)
        self.labels_action.setCheckable(True)
        self.labels_action.setChecked(True)
        self.labels_action.toggled.connect(self._toggle_orientation_labels)
        tb.addAction(self.labels_action)

    def _build_left_dock(self):
        dock = QtWidgets.QDockWidget("Project", self)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_tree_click)
        dock.setWidget(self.tree)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)

    def _build_right_dock(self):
        dock = QtWidgets.QDockWidget("Inspector", self)
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        self.name_edit = QtWidgets.QLineEdit()
        self.dim_x = QtWidgets.QSpinBox()
        self.dim_y = QtWidgets.QSpinBox()
        self.dim_z = QtWidgets.QSpinBox()
        for sb in (self.dim_x, self.dim_y, self.dim_z):
            sb.setRange(1, 5_000_000)
            sb.setSingleStep(100)
        form.addRow("Project name", self.name_edit)
        form.addRow("Dim X (mm)", self.dim_x)
        form.addRow("Dim Y (mm)", self.dim_y)
        form.addRow("Dim Z (mm)", self.dim_z)
        apply_btn = QtWidgets.QPushButton("Apply project settings")
        apply_btn.clicked.connect(self._apply_project_settings)
        form.addRow(apply_btn)
        align_btn = QtWidgets.QPushButton("Align model to tank")
        align_btn.clicked.connect(self._align_to_tank)
        form.addRow(align_btn)
        center_btn = QtWidgets.QPushButton("Center model in box")
        center_btn.clicked.connect(self._center_model_in_box)
        form.addRow(center_btn)
        form.addRow(QtWidgets.QLabel(" "))
        add_s = QtWidgets.QPushButton("Add sensor (+1 id)")
        add_s.clicked.connect(self.add_sensor)
        add_t = QtWidgets.QPushButton("Add tag")
        add_t.clicked.connect(self.add_tag)
        form.addRow(add_s)
        form.addRow(add_t)
        dock.setWidget(w)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

    def _make_table(self, headers):
        t = QtWidgets.QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setStretchLastSection(True)
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        return t

    def _build_bottom_dock(self):
        dock = QtWidgets.QDockWidget("Data", self)
        self.tabs = QtWidgets.QTabWidget()

        self.sensor_table = self._make_table(
            ["order", "id", "name", "x_mm", "y_mm", "z_mm", "tol", "status", "origin"])
        self.sensor_table.itemChanged.connect(self._on_sensor_changed)
        self.tabs.addTab(self._table_panel(self.sensor_table, self.add_sensor, self._del_sensor), "Sensors")

        self.tag_table = self._make_table(
            ["id", "size_mm", "x_mm", "y_mm", "z_mm", "plane", "origin"])
        self.tag_table.itemChanged.connect(self._on_tag_changed)
        self.tabs.addTab(self._table_panel(self.tag_table, self.add_tag, self._del_tag), "Tags")

        self.model_table = self._make_table(
            ["id", "file_name", "scale%", "off_x", "off_y", "off_z", "role", "visible"])
        self.model_table.itemChanged.connect(self._on_model_changed)
        self.tabs.addTab(self._table_panel(self.model_table, None, self._del_model), "Models")

        self.valid_list = QtWidgets.QListWidget()
        self.tabs.addTab(self.valid_list, "Validation")

        dock.setWidget(self.tabs)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

    def _table_panel(self, table, on_add, on_del):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(table)
        col = QtWidgets.QVBoxLayout()
        if on_add is not None:
            b = QtWidgets.QPushButton("Add")
            b.clicked.connect(on_add)
            col.addWidget(b)
        if on_del is not None:
            b = QtWidgets.QPushButton("Delete")
            b.clicked.connect(on_del)
            col.addWidget(b)
        col.addStretch(1)
        lay.addLayout(col)
        return w

    # --- refresh ----------------------------------------------------------

    def refresh_all(self):
        self.scene.set_project(self.project)
        self._load_inspector()
        self._load_tree()
        self._load_tables()
        self.scene.redraw()

    def _load_inspector(self):
        self._loading = True
        self.name_edit.setText(self.project.project_name)
        d = self.project.dimensions_mm
        self.dim_x.setValue(d[0])
        self.dim_y.setValue(d[1])
        self.dim_z.setValue(d[2])
        self._loading = False

    def _load_tree(self):
        self.tree.clear()
        root = QtWidgets.QTreeWidgetItem([self.project.project_name])
        self.tree.addTopLevelItem(root)
        for label in (f"Models ({len(self.project.stl_models)})",
                      f"Tags ({len(self.project.markers)})",
                      f"Sensors ({len(self.project.sensors)})",
                      "Coordinate Frame", "Validation"):
            root.addChild(QtWidgets.QTreeWidgetItem([label]))
        root.setExpanded(True)

    def _on_tree_click(self, item, _col):
        text = item.text(0)
        for key, idx in (("Sensors", 0), ("Tags", 1), ("Models", 2), ("Validation", 3)):
            if text.startswith(key):
                self.tabs.setCurrentIndex(idx)
                return

    def _load_tables(self):
        self._loading = True
        self._fill_sensor_table()
        self._fill_tag_table()
        self._fill_model_table()
        self._loading = False

    def _fill_sensor_table(self):
        t = self.sensor_table
        t.setRowCount(0)
        for s in sorted(self.project.sensors, key=lambda s: s.order):
            r = t.rowCount()
            t.insertRow(r)
            for c, v in enumerate([s.order, s.id, s.name, s.position_mm[0], s.position_mm[1],
                                   s.position_mm[2], s.tolerance_mm]):
                it = QtWidgets.QTableWidgetItem(str(v))
                if c == 0:
                    _noedit(it)
                t.setItem(r, c, it)
            t.setCellWidget(r, 7, self._combo(_STATUS_OPTS, s.status.value,
                                              lambda text, o=s: self._set_sensor_status(o, text)))
            t.setCellWidget(r, 8, self._combo(_ORIGIN_OPTS, s.origin.value,
                                              lambda text, o=s: self._set_sensor_origin(o, text)))

    def _fill_tag_table(self):
        t = self.tag_table
        t.setRowCount(0)
        for m in self.project.markers:
            r = t.rowCount()
            t.insertRow(r)
            for c, v in enumerate([m.id, m.size_mm, m.position_mm[0], m.position_mm[1], m.position_mm[2]]):
                t.setItem(r, c, QtWidgets.QTableWidgetItem(str(v)))
            plane = geo.plane_of_point(m.position_mm, self.project.dimensions_mm, tol=2.0)
            t.setCellWidget(r, 5, self._combo(_PLANE_OPTS, plane.value if plane else _PLANE_OPTS[0],
                                              lambda text, o=m: self._set_tag_plane(o, text)))
            t.setCellWidget(r, 6, self._combo(_ORIGIN_OPTS, m.origin.value,
                                              lambda text, o=m: self._set_tag_origin(o, text)))

    def _fill_model_table(self):
        t = self.model_table
        t.setRowCount(0)
        for m in self.project.stl_models:
            r = t.rowCount()
            t.insertRow(r)
            for c, v in enumerate([m.id, m.file_name, m.scale_percent,
                                   m.offset_mm[0], m.offset_mm[1], m.offset_mm[2]]):
                it = QtWidgets.QTableWidgetItem(str(v))
                if c in (0, 1):
                    _noedit(it)
                t.setItem(r, c, it)
            t.setCellWidget(r, 6, self._combo(_ROLE_OPTS, m.role,
                                              lambda text, o=m: self._set_model_role(o, text)))
            t.setCellWidget(r, 7, self._combo(_YESNO_OPTS, "yes" if m.visible else "no",
                                              lambda text, o=m: self._set_model_visible(o, text)))

    # --- table edits ------------------------------------------------------

    def _on_sensor_changed(self, item):
        if self._loading:
            return
        sensors = sorted(self.project.sensors, key=lambda s: s.order)
        if item.row() >= len(sensors):
            return
        s = sensors[item.row()]
        txt = item.text().strip()
        try:
            col = item.column()
            if col == 1:
                s.id = txt
            elif col == 2:
                s.name = txt
            elif col in (3, 4, 5):
                s.position_mm[col - 3] = int(float(txt))
            elif col == 6:
                s.tolerance_mm = int(float(txt))
        except ValueError:
            self._load_tables()
            return
        self.scene.redraw()

    def _on_tag_changed(self, item):
        if self._loading:
            return
        if item.row() >= len(self.project.markers):
            return
        m = self.project.markers[item.row()]
        txt = item.text().strip()
        try:
            col = item.column()
            if col == 0:
                m.id = int(float(txt))
            elif col == 1:
                m.size_mm = int(float(txt))
            elif col in (2, 3, 4):
                m.position_mm[col - 2] = int(float(txt))
        except ValueError:
            self._load_tables()
            return
        plane = geo.plane_of_point(m.position_mm, self.project.dimensions_mm, tol=2.0)
        if plane is not None:
            m.rotation_deg = list(geo.tag_rotation_for(plane))
            cb = self.tag_table.cellWidget(item.row(), 5)
            if cb is not None:
                self._loading = True
                cb.setCurrentText(plane.value)
                self._loading = False
        self.scene.redraw()

    def _on_model_changed(self, item):
        if self._loading:
            return
        if item.row() >= len(self.project.stl_models):
            return
        m = self.project.stl_models[item.row()]
        txt = item.text().strip()
        try:
            col = item.column()
            if col == 2:
                m.scale_percent = max(1, int(float(txt)))
            elif col in (3, 4, 5):
                m.offset_mm[col - 3] = int(float(txt))
        except ValueError:
            self._load_tables()
            return
        self.scene.redraw()

    # --- dropdowns & auto-align ------------------------------------------

    def _combo(self, options, value, on_change):
        cb = QtWidgets.QComboBox()
        cb.addItems(options)
        if str(value) in options:
            cb.setCurrentText(str(value))
        cb.currentTextChanged.connect(on_change)
        return cb

    def _set_sensor_status(self, s, text):
        if self._loading:
            return
        try:
            s.status = SensorStatus(text)
        except ValueError:
            return
        self.scene.redraw()

    def _set_sensor_origin(self, s, text):
        if self._loading:
            return
        try:
            s.origin = PlacementOrigin(text)
        except ValueError:
            return

    def _set_tag_origin(self, m, text):
        if self._loading:
            return
        try:
            m.origin = PlacementOrigin(text)
        except ValueError:
            return

    def _set_tag_plane(self, m, text):
        if self._loading:
            return
        try:
            plane = geo.TagPlane(text)
        except ValueError:
            return
        d = self.project.dimensions_mm
        u_max, v_max = geo.plane_uv_extent(plane, d)
        pos = geo.tag_position_for(plane, u_max / 2, v_max / 2, d, m.size_mm)
        m.position_mm = [int(round(x)) for x in pos]
        m.rotation_deg = list(geo.tag_rotation_for(plane))
        row = self.project.markers.index(m)
        self._loading = True
        for col, val in zip((2, 3, 4), m.position_mm):
            it = self.tag_table.item(row, col)
            if it is not None:
                it.setText(str(val))
        self._loading = False
        self.scene.redraw()

    def _set_model_role(self, m, text):
        if self._loading:
            return
        m.role = text

    def _set_model_visible(self, m, text):
        if self._loading:
            return
        m.visible = (text == "yes")
        self.scene.redraw()

    def _model_union_bounds(self):
        mn = mx = None
        for m in self.project.stl_models:
            pv_mesh = self.scene.meshes.get(m.file_name)
            if pv_mesh is None:
                continue
            b = pv_mesh.bounds
            lo = np.array([b[0], b[2], b[4]])
            hi = np.array([b[1], b[3], b[5]])
            mn = lo if mn is None else np.minimum(mn, lo)
            mx = hi if mx is None else np.maximum(mx, hi)
        return mn, mx

    def _align_to_tank(self):
        """Align the assembly from the TANK reference, matching the ARsens app (buildTankFrame /
        placeInTankFrame). Each part's WALL box (``core_bounds``) — not its full bbox — drives the
        fit, so ribbing/radiators/protrusions on the cover don't inflate the box or lift the cover:
        the box becomes the tank wall box (height extended to the cover top), the cover flange rests
        on the tank rim, interior parts sit on the floor. NO rescaling — the STL is in millimetres."""
        parts = []
        for m in self.project.stl_models:
            pv_mesh = self.scene.meshes.get(m.file_name)
            if pv_mesh is None:
                continue
            b = pv_mesh.bounds  # (xmin, xmax, ymin, ymax, zmin, zmax)
            full = (b[0], b[2], b[4], b[1], b[3], b[5])
            cached = self.core_bounds.get(m.file_name)
            core = tuple(float(v) for v in cached) if cached is not None else full
            role = str(m.role).upper()
            if role not in geo.WIRE_ROLES:
                role = geo.ROLE_OTHER
            parts.append(geo.PartGeom(
                id=m.id, role=role, name=m.name, scale_percent=m.scale_percent,
                full_bounds=full, core_bounds=core,
                rotation_deg=tuple(m.rotation_deg), offset_mm=tuple(m.offset_mm)))
        if not parts:
            self.statusBar().showMessage("No loaded model to align.")
            return
        placement = geo.solve_assembly_alignment(
            parts, adopt_dims=True, dims_locked=self.project.dimensions_locked,
            current_dims=self.project.dimensions_mm)
        if placement is None:
            self.statusBar().showMessage("No loaded model to align.")
            return
        self.project.dimensions_mm = list(placement.dims)
        for m in self.project.stl_models:
            off = placement.offsets.get(m.id)
            if off is not None:
                m.offset_mm = list(off)
        self.refresh_all()
        tank = next((m for m in self.project.stl_models if m.id == placement.tank_id), None)
        d = placement.dims
        manual = [m.name or m.id for m in self.project.stl_models if m.id in placement.manual_ids]
        manual_note = f" · place by hand: {', '.join(manual)}" if manual else ""
        lock_note = " (dims locked)" if self.project.dimensions_locked else ""
        self.statusBar().showMessage(
            f"Aligned to tank '{(tank.name if tank else '?')}': "
            f"box {d[0]}x{d[1]}x{d[2]} mm{lock_note}{manual_note}.")

    def _center_model_in_box(self):
        mn, mx = self._model_union_bounds()
        if mn is None:
            self.statusBar().showMessage("No loaded model to align.")
            return
        s = self.project.stl_models[0].scale_percent / 100.0 if self.project.stl_models else 1.0
        center = (mn + mx) / 2.0 * s
        d = np.array(self.project.dimensions_mm, dtype=float)
        off = d / 2.0 - center
        for m in self.project.stl_models:
            m.offset_mm = [int(round(off[0])), int(round(off[1])), int(round(off[2]))]
        self.refresh_all()
        self.statusBar().showMessage("Centered model in box.")

    # --- actions ----------------------------------------------------------

    def _next_sensor_num(self):
        nums = [int(s.id[1:]) for s in self.project.sensors if s.id[1:].isdigit() and s.id[:1] == "S"]
        nums += [int(s.id) for s in self.project.sensors if s.id.isdigit()]
        return (max(nums) if nums else 0) + 1

    def add_sensor(self):
        d = self.project.dimensions_mm
        order = max((s.order for s in self.project.sensors), default=0) + 1
        sid = f"S{self._next_sensor_num():03d}"
        self.project.sensors.append(Sensor(order=order, id=sid, name="Sensor",
                                           position_mm=[d[0] // 2, d[1] // 2, d[2] // 2], tolerance_mm=50))
        self.refresh_all()
        self.statusBar().showMessage(f"Added sensor {sid}")

    def add_tag(self):
        d = self.project.dimensions_mm
        tid = max((m.id for m in self.project.markers), default=0) + 1
        pos = geo.tag_position_for(geo.TagPlane.FRONT, d[0] / 2, d[2] / 2, d, 100)
        self.project.markers.append(Marker(id=tid, position_mm=[int(round(x)) for x in pos],
                                           size_mm=100, rotation_deg=list(geo.tag_rotation_for(geo.TagPlane.FRONT))))
        self.refresh_all()
        self.statusBar().showMessage(f"Added tag {tid}")

    def _del_sensor(self):
        rows = sorted({i.row() for i in self.sensor_table.selectedItems()})
        sensors = sorted(self.project.sensors, key=lambda s: s.order)
        for r in reversed(rows):
            if r < len(sensors):
                self.project.sensors.remove(sensors[r])
        self.refresh_all()

    def _del_tag(self):
        rows = sorted({i.row() for i in self.tag_table.selectedItems()})
        for r in reversed(rows):
            if r < len(self.project.markers):
                del self.project.markers[r]
        self.refresh_all()

    def _del_model(self):
        rows = sorted({i.row() for i in self.model_table.selectedItems()})
        for r in reversed(rows):
            if r < len(self.project.stl_models):
                m = self.project.stl_models[r]
                self.scene.remove_mesh(m.file_name)
                self.model_sources.pop(m.file_name, None)
                self.core_bounds.pop(m.file_name, None)
                del self.project.stl_models[r]
        self.refresh_all()

    def _apply_project_settings(self):
        self.project.project_name = self.name_edit.text().strip() or "New project"
        self.project.dimensions_mm = [self.dim_x.value(), self.dim_y.value(), self.dim_z.value()]
        self.refresh_all()

    def new_project(self):
        self.project = Project(project_name="New project")
        self.model_sources.clear()
        self.core_bounds.clear()
        self.scene.meshes.clear()
        self.refresh_all()

    def open_project(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open project", "", "ARsens project (*.json)")
        if not path:
            return
        try:
            self.project = json_io.load_project(path)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Open failed", str(exc))
            return
        self.scene.meshes.clear()
        self.model_sources.clear()
        self.core_bounds.clear()
        self.refresh_all()
        self.statusBar().showMessage(f"Opened {path} (re-import models to see geometry)")

    def save_project(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save project JSON", "project.json", "JSON (*.json)")
        if not path:
            return
        json_io.save_project(self.project, path)
        self.statusBar().showMessage(f"Saved {path}")

    def import_model(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import 3D model", "", _MODEL_FILTER)
        if not path:
            return
        try:
            tm = mesh_loader.load_mesh(path)
            pv_mesh = mesh_loader.to_pyvista(tm)
            core = mesh_loader.core_bounds(tm)  # wall box, cached now (mesh itself is dropped)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Import failed", str(exc))
            return
        name = Path(path).name
        role = geo.detect_role_from_name(Path(path).stem)
        self.model_sources[name] = path
        self.core_bounds[name] = core
        if not any(m.file_name == name for m in self.project.stl_models):
            self.project.stl_models.append(StlModel(id=name, name=Path(path).stem, file_name=name, role=role))
        self.project.model_file = name
        self.scene.set_mesh(name, pv_mesh)
        self.refresh_all()
        self.statusBar().showMessage(f"Loaded {name} ({role})")

    def import_excel(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import Excel", "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            self.project = excel_io.read_workbook(path)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Import failed", str(exc))
            return
        self.refresh_all()
        self.statusBar().showMessage(f"Imported {path}")

    def export_excel(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export Excel template", "project_template.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        excel_io.write_workbook(self.project, path, validation.validate_project(self.project))
        self.statusBar().showMessage(f"Wrote {path}")

    def export_package(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export package", "arsens_project_export.zip", "Zip (*.zip)")
        if not path:
            return
        try:
            export_package.build_export(self.project, path, self.model_sources,
                                        validation.validate_project(self.project, model_bounds=self._model_bounds()))
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Export failed", str(exc))
            return
        QtWidgets.QMessageBox.information(self, "Exported", f"Package written:\n{path}")

    def validate(self):
        issues = validation.validate_project(self.project, model_bounds=self._model_bounds())
        self.valid_list.clear()
        if not issues:
            self.valid_list.addItem("No problems found.")
        for issue in issues:
            li = QtWidgets.QListWidgetItem(str(issue))
            li.setForeground(QtGui.QColor(_ERROR_RED if issue.level == "error" else _WARN_AMBER))
            self.valid_list.addItem(li)
        self.tabs.setCurrentWidget(self.valid_list)

    def _model_bounds(self):
        out = {}
        for name, pv_mesh in self.scene.meshes.items():
            b = pv_mesh.bounds
            out[name] = (b[1] - b[0], b[3] - b[2], b[5] - b[4])
        return out

    def _enable_surface_pick(self, callback, msg, owner):
        self._disable_pick()  # ensure a single active picker (the two modes are exclusive)
        try:
            self.interactor.enable_surface_point_picking(
                callback=callback, show_message=True, left_clicking=True, show_point=True)
            self.statusBar().showMessage(msg)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Picking unavailable: {exc}")
            owner.setChecked(False)

    def _disable_pick(self):
        try:
            self.interactor.disable_picking()
        except Exception:
            pass

    def _uncheck_silently(self, action):
        action.blockSignals(True)
        action.setChecked(False)
        action.blockSignals(False)

    def _toggle_pick(self, checked):
        # Sensor and tag click-place are mutually exclusive (one VTK picker at a time).
        if checked:
            self._uncheck_silently(self.pick_tag_action)
            self._enable_surface_pick(self._on_pick, "Click a surface to drop a sensor.", self.pick_action)
        else:
            self._disable_pick()

    def _toggle_pick_tag(self, checked):
        if checked:
            self._uncheck_silently(self.pick_action)
            self._enable_surface_pick(
                self._on_tag_pick, "Click a wall to drop a tag (plane auto-detected).", self.pick_tag_action)
        else:
            self._disable_pick()

    def _toggle_orientation_labels(self, checked):
        self.scene.show_orientation_labels = checked
        self.scene.redraw()

    def _on_tag_pick(self, point, *_args):
        if point is None:
            return
        d = self.project.dimensions_mm
        plane = geo.nearest_plane(point, d)
        size = 100
        u, v = geo.tag_uv_of_point(plane, point)
        pos = geo.tag_position_for(plane, u, v, d, size)
        tid = max((m.id for m in self.project.markers), default=0) + 1
        self.project.markers.append(Marker(
            id=tid, position_mm=[int(round(x)) for x in pos], size_mm=size,
            rotation_deg=list(geo.tag_rotation_for(plane))))
        self.refresh_all()
        self.statusBar().showMessage(
            f"Placed tag #{tid} on {plane.value} at {[int(round(x)) for x in pos]} mm")

    def _on_pick(self, point, *_args):
        if point is None:
            return
        d = self.project.dimensions_mm
        order = max((s.order for s in self.project.sensors), default=0) + 1
        sid = f"S{self._next_sensor_num():03d}"
        self.project.sensors.append(Sensor(order=order, id=sid, name="Sensor",
                                           position_mm=[int(round(point[0])), int(round(point[1])), int(round(point[2]))],
                                           tolerance_mm=50))
        self.refresh_all()
        self.statusBar().showMessage(f"Placed {sid} at {[int(round(x)) for x in point]} mm")
