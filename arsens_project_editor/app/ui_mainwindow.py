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
_PREVIEW_TAG_COLOR = "#13E3CE"  # ghost-preview colour for the tag place tool (matches viewport)

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
        self._drag = None            # active drag: {kind, obj, plane, axis, value, normal}
        self._drag_style = None      # custom VTK interactor style while "Select / move" is on
        self._move_fallback = False  # True when drag couldn't install → click-to-relocate instead
        self._measure_pts: list = [] # accumulates the two measure clicks
        self._panning = False        # left-drag pan in progress (2D lock)

        self.interactor = QtInteractor(self)
        self.setCentralWidget(self.interactor)
        self.scene = TransformerScene(self.interactor)
        self.scene.set_project(self.project)

        self._build_toolbar()
        self._build_left_dock()
        self._build_right_dock()
        self._build_tools_dock()
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
        # Interaction tools (place / select-move / measure / labels / 2D-lock / colours) live in the
        # right-side "Tools" dock — see _build_tools_dock.

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
        self._inspector_dock = dock
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

    def _build_tools_dock(self):
        """Right-side panel with the interaction tools, the 2D-lock controls and sensor-colour
        swatches. The tools reuse checkable QActions (so all toggle logic is unchanged) surfaced as
        QToolButtons."""
        self.pick_action = QtGui.QAction("Click-place sensor", self)
        self.pick_action.setCheckable(True)
        self.pick_action.toggled.connect(self._toggle_pick)
        self.pick_tag_action = QtGui.QAction("Click-place tag", self)
        self.pick_tag_action.setCheckable(True)
        self.pick_tag_action.toggled.connect(self._toggle_pick_tag)
        self.move_action = QtGui.QAction("Select / move", self)
        self.move_action.setCheckable(True)
        self.move_action.toggled.connect(self._toggle_move)
        self.measure_action = QtGui.QAction("Measure", self)
        self.measure_action.setCheckable(True)
        self.measure_action.toggled.connect(self._toggle_measure)
        self.labels_action = QtGui.QAction("Labels", self)
        self.labels_action.setCheckable(True)
        self.labels_action.setChecked(True)
        self.labels_action.toggled.connect(self._toggle_orientation_labels)

        dock = QtWidgets.QDockWidget("Tools", self)
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        for act in (self.pick_action, self.pick_tag_action, self.move_action,
                    self.measure_action, self.labels_action):
            btn = QtWidgets.QToolButton()
            btn.setDefaultAction(act)
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
            btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            lay.addWidget(btn)

        lay.addWidget(self._hline())
        lay.addWidget(QtWidgets.QLabel("2D lock (flat, plane-constrained)"))
        self.plane_combo = QtWidgets.QComboBox()
        self.plane_combo.addItems(_PLANE_OPTS)
        self.plane_combo.currentTextChanged.connect(self._on_lock_plane_changed)
        lay.addWidget(self.plane_combo)
        self.lock2d_check = QtWidgets.QCheckBox("Lock to this plane (2D)")
        self.lock2d_check.toggled.connect(self._toggle_2d_lock)
        lay.addWidget(self.lock2d_check)

        lay.addWidget(self._hline())
        lay.addWidget(QtWidgets.QLabel("Sensor colours (by status)"))
        self._color_btns = {}
        for key, label in (("pending", "Pending"), ("ok", "OK"), ("fail", "Fail")):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _checked=False, k=key: self._pick_status_color(k))
            lay.addWidget(b)
            self._color_btns[key] = b
        reset = QtWidgets.QPushButton("Reset colours")
        reset.clicked.connect(self._reset_status_colors)
        lay.addWidget(reset)

        lay.addWidget(self._hline())
        lay.addWidget(QtWidgets.QLabel("Background"))
        bg_row = QtWidgets.QHBoxLayout()
        white_btn = QtWidgets.QPushButton("White")
        white_btn.clicked.connect(lambda: self.scene.set_background_color("#FFFFFF"))
        dark_btn = QtWidgets.QPushButton("Dark")
        dark_btn.clicked.connect(lambda: self.scene.set_background_color("#0E1726"))
        choose_btn = QtWidgets.QPushButton("Choose…")
        choose_btn.clicked.connect(self._pick_background_color)
        bg_row.addWidget(white_btn)
        bg_row.addWidget(dark_btn)
        bg_row.addWidget(choose_btn)
        lay.addLayout(bg_row)
        lay.addStretch(1)

        dock.setWidget(w)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        try:
            self.splitDockWidget(self._inspector_dock, dock, QtCore.Qt.Vertical)
        except Exception:
            pass
        self._default_status_colors = dict(self.scene.status_colors)
        self._update_color_btns()

    def _hline(self):
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        return line

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

    def refresh_all(self, reset_camera: bool = False):
        self.scene.set_project(self.project)
        self._load_inspector()
        self._load_tree()
        self._load_tables()
        self.scene.redraw(reset_camera)

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
        self.refresh_all(reset_camera=True)
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
        self.refresh_all(reset_camera=True)
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
        self.refresh_all(reset_camera=True)

    def new_project(self):
        self.project = Project(project_name="New project")
        self.model_sources.clear()
        self.core_bounds.clear()
        self.scene.meshes.clear()
        self.refresh_all(reset_camera=True)

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
        self.refresh_all(reset_camera=True)
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
        self.refresh_all(reset_camera=True)
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
        self.refresh_all(reset_camera=True)
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

    def _disable_pick(self):
        try:
            self.interactor.disable_picking()
        except Exception:
            pass

    def _uncheck_silently(self, action):
        action.blockSignals(True)
        action.setChecked(False)
        action.blockSignals(False)

    def _all_tool_actions(self):
        return [self.pick_action, self.pick_tag_action, self.move_action, self.measure_action]

    def _begin_exclusive(self, keep):
        """Make [keep] the only checked tool (the four are mutually exclusive)."""
        for a in self._all_tool_actions():
            if a is not keep:
                self._uncheck_silently(a)

    def _apply_interaction(self):
        """Install the unified edit style whenever a tool OR 2D-lock is active — it owns left-click
        for place/select-move/measure, the cursor preview and left-drag pan (2D lock). Otherwise the
        plain trackball (orbit / middle-pan / scroll-zoom)."""
        self._disable_pick()
        self._remove_drag_style()  # restores trackball
        self.scene.clear_preview()
        active = (self.pick_action.isChecked() or self.pick_tag_action.isChecked()
                  or self.move_action.isChecked() or self.measure_action.isChecked()
                  or self._is_2d_locked())
        if active:
            self._install_edit_style()

    def _toggle_pick(self, checked):
        if checked:
            self._begin_exclusive(self.pick_action)
        self._apply_interaction()

    def _toggle_pick_tag(self, checked):
        if checked:
            self._begin_exclusive(self.pick_tag_action)
        self._apply_interaction()

    def _toggle_orientation_labels(self, checked):
        self.scene.show_orientation_labels = checked
        self.scene.redraw()

    # --- select / move tool ----------------------------------------------

    def _toggle_move(self, checked):
        if checked:
            self._begin_exclusive(self.move_action)
            self.statusBar().showMessage("Select / move: click a sensor or tag, then drag it in its plane.")
        else:
            self.scene.clear_selection()
        self._apply_interaction()

    # --- 2D lock (flat view + plane-constrained add/move/measure) ----------

    def _current_lock_plane(self):
        try:
            return geo.TagPlane(self.plane_combo.currentText())
        except Exception:
            return geo.TagPlane.FRONT

    def _on_lock_plane_changed(self, _text):
        if getattr(self, "lock2d_check", None) and self.lock2d_check.isChecked():
            self._apply_2d_lock_view(True)
            self._apply_interaction()

    def _toggle_2d_lock(self, checked):
        self._apply_2d_lock_view(checked)
        self._apply_interaction()
        self.statusBar().showMessage(
            f"2D lock on: {self._current_lock_plane().value} plane — placing/moving stays on it"
            if checked else "2D lock off")

    def _apply_2d_lock_view(self, on):
        plane = self._current_lock_plane()
        if on:
            try:
                self.interactor.enable_parallel_projection()
            except Exception:
                pass
            self.scene.view(plane.value)        # look straight at the plane
            self.scene.set_pick_plane(plane)    # full-face surface to click on
        else:
            self.scene.clear_pick_plane()
            try:
                self.interactor.disable_parallel_projection()
            except Exception:
                pass

    def _is_2d_locked(self) -> bool:
        return bool(getattr(self, "lock2d_check", None) and self.lock2d_check.isChecked())

    def _install_edit_style(self) -> bool:
        """One trackball-based style for all tools: left-press on a marker drags it; with a place/
        measure tool it acts at the point under the cursor; on empty space it pans (2D lock) or
        orbits (3D). Mouse-move shows the placement preview. False if VTK won't allow it."""
        try:
            import vtk
            win = self

            class _EditStyle(vtk.vtkInteractorStyleTrackballCamera):
                def __init__(self):
                    super().__init__()
                    self.AddObserver("LeftButtonPressEvent", self._press)
                    self.AddObserver("MouseMoveEvent", self._move)
                    self.AddObserver("LeftButtonReleaseEvent", self._release)

                def _press(self, obj, evt):
                    x, y = self.GetInteractor().GetEventPosition()
                    if win._on_edit_press(x, y):
                        return  # consumed (drag / place / measure)
                    if win._is_2d_locked():
                        self.StartPan(); win._panning = True; return  # left-drag pans in 2D
                    self.OnLeftButtonDown()  # orbit in 3D

                def _move(self, obj, evt):
                    if win._drag is not None:
                        x, y = self.GetInteractor().GetEventPosition()
                        win._drag_to(x, y); return
                    if win._panning:
                        self.Pan(); return
                    x, y = self.GetInteractor().GetEventPosition()
                    win._update_preview(x, y)
                    self.OnMouseMove()

                def _release(self, obj, evt):
                    if win._drag is not None:
                        win._end_drag(); return
                    if win._panning:
                        self.EndPan(); win._panning = False; return
                    self.OnLeftButtonUp()

            style = _EditStyle()
            self.interactor.GetRenderWindow().GetInteractor().SetInteractorStyle(style)
            self._drag_style = style
            return True
        except Exception:
            self._drag_style = None
            return False

    def _on_edit_press(self, x, y) -> bool:
        if self.move_action.isChecked():
            item = self._pick_item_at(x, y)
            if item is not None:
                self._begin_drag(item)
                return True
            return False
        pt = self._point_under_cursor(x, y)
        if pt is None:
            return False
        if self.pick_action.isChecked():
            self._place_sensor(pt); return True
        if self.pick_tag_action.isChecked():
            self._place_tag(pt); return True
        if self.measure_action.isChecked():
            self._add_measure_point(pt); return True
        return False

    def _point_under_cursor(self, x, y):
        """Where a click lands: on the locked plane (2D lock) or on the model surface (cell pick)."""
        if self._is_2d_locked():
            return self._plane_point_at(x, y)
        try:
            import vtk
            picker = vtk.vtkCellPicker()
            picker.SetTolerance(0.0005)
            if picker.Pick(int(x), int(y), 0, self.interactor.renderer):
                return np.asarray(picker.GetPickPosition(), dtype=float)
        except Exception:
            return None
        return None

    def _plane_point_at(self, x, y):
        ray = self._cursor_ray(x, y)
        if ray is None:
            return None
        near, far = ray
        plane = self._current_lock_plane()
        dims = [float(d) for d in self.project.dimensions_mm]
        axis, value = geo.plane_fixed_axis(plane, dims)
        normal = np.zeros(3)
        normal[axis] = 1.0
        p0 = np.zeros(3)
        p0[axis] = value
        return geo.ray_plane_intersection(near, far, p0, normal)

    def _update_preview(self, x, y):
        if not (self.pick_action.isChecked() or self.pick_tag_action.isChecked()):
            self.scene.clear_preview()
            return
        pt = self._point_under_cursor(x, y)
        if pt is None:
            self.scene.clear_preview()
            return
        color = _PREVIEW_TAG_COLOR if self.pick_tag_action.isChecked() \
            else self.scene.status_colors.get(SensorStatus.PENDING, "#888888")
        self.scene.set_preview(pt, color)

    def _place_sensor(self, point):
        dims = [float(d) for d in self.project.dimensions_mm]
        if self._is_2d_locked():
            point = geo.project_point_to_plane(point, self._current_lock_plane(), dims)
        p = np.asarray(point, dtype=float)
        pos = [int(round(float(np.clip(p[i], 0.0, dims[i])))) for i in range(3)]
        order = max((s.order for s in self.project.sensors), default=0) + 1
        sid = f"S{self._next_sensor_num():03d}"
        self.project.sensors.append(Sensor(order=order, id=sid, name="Sensor",
                                           position_mm=pos, tolerance_mm=50))
        self.refresh_all()
        self.statusBar().showMessage(f"Placed {sid} at {pos} mm")

    def _place_tag(self, point):
        dims = [float(d) for d in self.project.dimensions_mm]
        plane = self._current_lock_plane() if self._is_2d_locked() else geo.nearest_plane(point, dims)
        u, v = geo.tag_uv_of_point(plane, point)
        pos = geo.tag_position_for(plane, u, v, dims, 100)
        tid = max((m.id for m in self.project.markers), default=0) + 1
        self.project.markers.append(Marker(id=tid, position_mm=[int(round(x)) for x in pos],
                                           size_mm=100, rotation_deg=list(geo.tag_rotation_for(plane))))
        self.refresh_all()
        self.statusBar().showMessage(f"Placed tag #{tid} on {plane.value}")

    def _add_measure_point(self, point):
        dims = [float(d) for d in self.project.dimensions_mm]
        self._measure_pts.append(self._snap_to_item(point, dims))
        if len(self._measure_pts) < 2:
            self.statusBar().showMessage("Measure: click the second point.")
            return
        p1, p2 = self._measure_pts[-2], self._measure_pts[-1]
        drop = self._view_depth_axis()
        self.scene.set_measure(p1, p2, drop)
        d_a, d_b, diag, (a, b) = geo.inplane_deltas(p1, p2, drop)
        letters = ["X", "Y", "Z"]
        self.statusBar().showMessage(
            f"Δ{letters[a]} {d_a:.0f} · Δ{letters[b]} {d_b:.0f} · direct {diag:.0f} mm")
        self._measure_pts = []

    def _remove_drag_style(self):
        if self._drag_style is None:
            return
        self._drag_style = None
        self._drag = None
        self._panning = False
        try:
            self.interactor.enable_trackball_style()
        except Exception:
            try:
                import vtk
                self.interactor.GetRenderWindow().GetInteractor().SetInteractorStyle(
                    vtk.vtkInteractorStyleTrackballCamera())
            except Exception:
                pass

    def _pick_item_at(self, x, y):
        """The (kind, object) of the sensor/tag marker under display point (x, y), or None."""
        try:
            import vtk
            picker = vtk.vtkPropPicker()
            picker.PickProp(int(x), int(y), self.interactor.renderer)
            actor = picker.GetViewProp()
            if actor is None:
                return None
            for sid, handles in self.scene.sensor_actors.items():
                if any(a is actor for a, _ in handles):
                    s = next((o for o in self.project.sensors if o.id == sid), None)
                    return ("sensor", s) if s is not None else None
            for tid, handles in self.scene.tag_actors.items():
                if any(a is actor for a, _ in handles):
                    m = next((o for o in self.project.markers if o.id == tid), None)
                    return ("tag", m) if m is not None else None
        except Exception:
            return None
        return None

    def _begin_drag(self, item):
        kind, obj = item
        dims = [float(d) for d in self.project.dimensions_mm]
        if kind == "tag":
            plane = geo.plane_of_point(obj.position_mm, dims, tol=3.0) \
                or geo.nearest_plane(obj.position_mm, dims)
            axis, value = geo.plane_fixed_axis(plane, dims)
        else:
            plane = geo.nearest_plane(obj.position_mm, dims)
            axis, _ = geo.plane_fixed_axis(plane, dims)
            value = float(obj.position_mm[axis])  # sensor slides at its current depth
        normal = np.zeros(3)
        normal[axis] = 1.0
        self._drag = {"kind": kind, "obj": obj, "plane": plane, "axis": axis,
                      "value": value, "normal": normal}
        # Halo only — no full rebuild. Actor handles already exist from the last structural redraw.
        self.scene.set_selection(kind, obj.id)

    def _drag_to(self, x, y):
        drag = self._drag
        if drag is None:
            return
        ray = self._cursor_ray(x, y)
        if ray is None:
            return
        near, far = ray
        obj = drag["obj"]
        hit = geo.ray_plane_intersection(
            near, far, np.asarray(obj.position_mm, dtype=float), drag["normal"])
        if hit is None:
            return
        dims = [float(d) for d in self.project.dimensions_mm]
        if drag["kind"] == "tag":
            u, v = geo.tag_uv_of_point(drag["plane"], hit)
            pos = geo.tag_position_for(drag["plane"], u, v, dims, obj.size_mm)
            new = [int(round(float(pos[i]))) for i in range(3)]
        else:
            h = np.asarray(hit, dtype=float)
            h[drag["axis"]] = drag["value"]  # keep it on its plane
            new = [int(round(float(np.clip(h[i], 0.0, dims[i])))) for i in range(3)]
        obj.position_mm = new
        self.scene.translate_item(drag["kind"], obj.id, new)
        self._show_live_drag(drag["kind"], obj, new)

    def _end_drag(self):
        moved = self._drag
        self._drag = None
        self.refresh_all()  # rebuild + sync tables; camera preserved
        if moved is not None:
            self.statusBar().showMessage(
                f"Moved {moved['kind']} to {list(moved['obj'].position_mm)} mm")

    def _cursor_ray(self, x, y):
        """Near/far world points of the cursor ray (unprojected display point at z=0 and z=1)."""
        try:
            ren = self.interactor.renderer
            ren.SetDisplayPoint(float(x), float(y), 0.0)
            ren.DisplayToWorld()
            w0 = ren.GetWorldPoint()
            ren.SetDisplayPoint(float(x), float(y), 1.0)
            ren.DisplayToWorld()
            w1 = ren.GetWorldPoint()
            if abs(w0[3]) < 1e-12 or abs(w1[3]) < 1e-12:
                return None
            near = np.array([w0[0] / w0[3], w0[1] / w0[3], w0[2] / w0[3]])
            far = np.array([w1[0] / w1[3], w1[1] / w1[3], w1[2] / w1[3]])
            return near, far
        except Exception:
            return None

    # --- measure tool ----------------------------------------------------

    def _toggle_measure(self, checked):
        if checked:
            self._begin_exclusive(self.measure_action)
        self._measure_pts = []
        self.scene.clear_measure()
        self._apply_interaction()

    def _snap_to_item(self, point, dims):
        pts = [list(s.position_mm) for s in self.project.sensors] \
            + [list(m.position_mm) for m in self.project.markers]
        thr = max(50.0, min(dims) * 0.03) if min(dims) > 0 else 50.0
        idx = geo.nearest_index(point, pts, thr)
        if idx is not None:
            return [float(v) for v in pts[idx]]
        return [float(point[0]), float(point[1]), float(point[2])]

    def _view_depth_axis(self) -> int:
        try:
            return geo.dominant_axis(self.interactor.camera.GetDirectionOfProjection())
        except Exception:
            return 1  # default: drop Y (front-on view)

    def _show_live_drag(self, kind, obj, new):
        """Live status during a drag: the item's position + Δ to the nearest other sensor/tag."""
        label = obj.id if kind == "sensor" else f"#{obj.id}"
        msg = f"{kind} {label} @ {list(new)} mm"
        other = self._nearest_other_point(kind, obj, new)
        if other is not None:
            d_a, d_b, diag, (a, b) = geo.inplane_deltas(new, other, self._view_depth_axis())
            letters = ["X", "Y", "Z"]
            msg += f"  ·  nearest Δ{letters[a]} {d_a:.0f} Δ{letters[b]} {d_b:.0f} d {diag:.0f}"
        self.statusBar().showMessage(msg)

    def _nearest_other_point(self, kind, obj, new):
        pts = [list(s.position_mm) for s in self.project.sensors
               if not (kind == "sensor" and s.id == obj.id)]
        pts += [list(m.position_mm) for m in self.project.markers
                if not (kind == "tag" and m.id == obj.id)]
        if not pts:
            return None
        idx = geo.nearest_index(new, pts, 1e12)
        return [float(v) for v in pts[idx]] if idx is not None else None

    # --- sensor-status colours -------------------------------------------

    def _pick_status_color(self, key):
        keymap = {"pending": SensorStatus.PENDING, "ok": SensorStatus.OK, "fail": SensorStatus.FAIL}
        status = keymap[key]
        current = self.scene.status_colors.get(status, "#888888")
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(current), self, f"{key.title()} colour")
        if col.isValid():
            self.scene.status_colors[status] = col.name()
            self._update_color_btns()
            self.scene.redraw()

    def _reset_status_colors(self):
        self.scene.status_colors = dict(self._default_status_colors)
        self._update_color_btns()
        self.scene.redraw()

    def _update_color_btns(self):
        if not hasattr(self, "_color_btns"):
            return
        keymap = {"pending": SensorStatus.PENDING, "ok": SensorStatus.OK, "fail": SensorStatus.FAIL}
        for key, btn in self._color_btns.items():
            c = self.scene.status_colors.get(keymap[key], "#888888")
            btn.setStyleSheet(f"background-color: {c}; color: #0E1726; font-weight: bold;")

    def _pick_background_color(self):
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.scene.bg_color), self, "Background colour")
        if col.isValid():
            self.scene.set_background_color(col.name())
