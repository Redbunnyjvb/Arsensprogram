"""PySide6 main window: toolbar, project tree, inspector, 3D viewport, data tables, validation log."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from pyvistaqt import QtInteractor

from . import excel_io, export_package, json_io, mesh_loader, validation
from . import geometry as geo
from .models import Marker, Project, Sensor, StlModel
from .viewport import TransformerScene

_ERROR_RED = "#D32F2F"
_WARN_AMBER = "#C9851F"


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
        box_btn = QtWidgets.QPushButton("Box = model bounding box")
        box_btn.clicked.connect(self._box_from_model)
        form.addRow(box_btn)
        form.addRow(QtWidgets.QLabel(" "))
        add_s = QtWidgets.QPushButton("Add sensor (+1 id)")
        add_s.clicked.connect(self.add_sensor)
        add_t = QtWidgets.QPushButton("Add tag (Front)")
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
            ["id", "file_name", "scale%", "off_x", "off_y", "off_z", "visible"])
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
            cells = [s.order, s.id, s.name, s.position_mm[0], s.position_mm[1], s.position_mm[2],
                     s.tolerance_mm, s.status.value, s.origin.value]
            for c, v in enumerate(cells):
                it = QtWidgets.QTableWidgetItem(str(v))
                if c in (0, 7, 8):
                    _noedit(it)
                t.setItem(r, c, it)

    def _fill_tag_table(self):
        t = self.tag_table
        t.setRowCount(0)
        for m in self.project.markers:
            r = t.rowCount()
            t.insertRow(r)
            plane = geo.plane_of_point(m.position_mm, self.project.dimensions_mm, tol=2.0)
            cells = [m.id, m.size_mm, m.position_mm[0], m.position_mm[1], m.position_mm[2],
                     plane.value if plane else "-", m.origin.value]
            for c, v in enumerate(cells):
                it = QtWidgets.QTableWidgetItem(str(v))
                if c in (5, 6):
                    _noedit(it)
                t.setItem(r, c, it)

    def _fill_model_table(self):
        t = self.model_table
        t.setRowCount(0)
        for m in self.project.stl_models:
            r = t.rowCount()
            t.insertRow(r)
            cells = [m.id, m.file_name, m.scale_percent,
                     m.offset_mm[0], m.offset_mm[1], m.offset_mm[2], "yes" if m.visible else "no"]
            for c, v in enumerate(cells):
                it = QtWidgets.QTableWidgetItem(str(v))
                if c in (0, 1):
                    _noedit(it)
                t.setItem(r, c, it)

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
        self._load_tables()
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
            elif col == 6:
                m.visible = txt.lower() in ("yes", "ja", "true", "1")
        except ValueError:
            self._load_tables()
            return
        self.scene.redraw()

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
                del self.project.stl_models[r]
        self.refresh_all()

    def _apply_project_settings(self):
        self.project.project_name = self.name_edit.text().strip() or "New project"
        self.project.dimensions_mm = [self.dim_x.value(), self.dim_y.value(), self.dim_z.value()]
        self.refresh_all()

    def new_project(self):
        self.project = Project(project_name="New project")
        self.model_sources.clear()
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
        self.refresh_all()
        self.statusBar().showMessage(f"Opened {path} (re-import models to see geometry)")

    def save_project(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save project JSON", "project.json", "JSON (*.json)")
        if not path:
            return
        json_io.save_project(self.project, path)
        self.statusBar().showMessage(f"Saved {path}")

    def import_model(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import 3D model", "", "3D models (*.stl *.obj *.ply)")
        if not path:
            return
        try:
            pv_mesh = mesh_loader.to_pyvista(mesh_loader.load_mesh(path))
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Import failed", str(exc))
            return
        name = Path(path).name
        self.model_sources[name] = path
        if not any(m.file_name == name for m in self.project.stl_models):
            self.project.stl_models.append(StlModel(id=name, name=Path(path).stem, file_name=name, role="body"))
        self.project.model_file = name
        self.scene.set_mesh(name, pv_mesh)
        self.refresh_all()
        self.statusBar().showMessage(f"Loaded {name}")

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

    def _box_from_model(self):
        mn = mx = None
        for m in self.project.stl_models:
            pv_mesh = self.scene.meshes.get(m.file_name)
            if pv_mesh is None:
                continue
            b = pv_mesh.bounds
            s = m.scale_percent / 100.0
            lo = np.array([b[0], b[2], b[4]]) * s
            hi = np.array([b[1], b[3], b[5]]) * s
            mn = lo if mn is None else np.minimum(mn, lo)
            mx = hi if mx is None else np.maximum(mx, hi)
        if mn is None:
            self.statusBar().showMessage("No loaded model to size the box from.")
            return
        span = [max(1, int(round(v))) for v in (mx - mn)]
        self.project.dimensions_mm = span
        for m in self.project.stl_models:
            m.offset_mm = [int(round(-mn[0])), int(round(-mn[1])), int(round(-mn[2]))]
        self.refresh_all()
        self.statusBar().showMessage(f"Box sized to model: {span[0]} x {span[1]} x {span[2]} mm")

    def _toggle_pick(self, checked):
        if checked:
            try:
                self.interactor.enable_surface_point_picking(
                    callback=self._on_pick, show_message=True, left_clicking=True, show_point=True)
                self.statusBar().showMessage("Click a surface to drop a sensor.")
            except Exception as exc:  # noqa: BLE001
                self.statusBar().showMessage(f"Picking unavailable: {exc}")
                self.pick_action.setChecked(False)
        else:
            try:
                self.interactor.disable_picking()
            except Exception:
                pass

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
