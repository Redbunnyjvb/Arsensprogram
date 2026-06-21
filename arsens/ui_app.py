"""Tkinter authoring GUI (orchestration/presentation layer only).

Lets you build/edit an ARsens project — dimensions, sensors and tags in XYZ — attach a 3D model,
see a top-view schematic, and export a one-file .arsenspkg the app imports directly. All data logic
lives in the adapters (model/project_json/project_excel/package/validation); this file only wires
widgets to them.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import mesh
from . import package as pkg
from . import project_excel as px
from . import project_json as pj
from . import validation as val
from .model import (
    FloatVector,
    Marker,
    MmPosition,
    PlacementOrigin,
    Project,
    Sensor,
    SensorStatus,
    StlModel,
)

# Sensor dot colours mirror the app: pending = orange (todo), ok = blue (placed), fail = red.
_STATUS_COLOUR = {
    SensorStatus.PENDING: "#F5B544",
    SensorStatus.OK: "#2F6FED",
    SensorStatus.FAIL: "#E0573B",
}
_TAG_COLOUR = "#19C3B2"
_MODEL_BASE_RGB = (122, 142, 174)


def _tri_normal(t):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    mag = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    return nx / mag, ny / mag, nz / mag


def _shade_hex(shade):
    # Same flat-shading the app uses (StlPreview.rasterizeMesh): base colour * shade.
    r, g, b = _MODEL_BASE_RGB
    return f"#{int(r * shade):02x}{int(g * shade):02x}{int(b * shade):02x}"


class _FieldDialog(tk.Toplevel):
    """Modal form: fields is a list of (key, label, kind, choices?). Result in self.result."""

    def __init__(self, parent, title, fields, initial):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self._fields = fields
        self._vars: dict[str, tk.StringVar] = {}

        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")
        for row, spec in enumerate(fields):
            key, label, kind = spec[0], spec[1], spec[2]
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            var = tk.StringVar(value=str(initial.get(key, "")))
            self._vars[key] = var
            if kind == "choice":
                ttk.Combobox(body, textvariable=var, values=spec[3], state="readonly", width=22).grid(
                    row=row, column=1, sticky="ew", pady=3)
            else:
                ttk.Entry(body, textvariable=var, width=24).grid(row=row, column=1, sticky="ew", pady=3)

        btns = ttk.Frame(self, padding=(12, 0, 12, 12))
        btns.grid(sticky="e")
        ttk.Button(btns, text="Annuleer", command=self._cancel).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="OK", command=self._ok).grid(row=0, column=1, padx=4)

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        out = {}
        try:
            for spec in self._fields:
                key, kind = spec[0], spec[2]
                raw = self._vars[key].get().strip()
                if kind == "int":
                    out[key] = int(float(raw)) if raw else 0
                elif kind == "float":
                    out[key] = float(raw) if raw else 0.0
                elif kind == "optint":
                    out[key] = int(float(raw)) if raw else None
                else:
                    out[key] = raw
        except ValueError:
            messagebox.showerror("Ongeldige invoer", "Controleer de getalvelden.", parent=self)
            return
        self.result = out
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class AuthoringApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.project = Project(project_name="Nieuw project")
        self.model_sources: dict[str, str] = {}   # file_name -> source path on disk
        self.path: Path | None = None
        self._tmpdir = tempfile.TemporaryDirectory(prefix="arsenspkg_")

        # Interactive-canvas state.
        self.view_var = tk.StringVar(value="top")
        self._preview_tris: list = []      # model triangles (box-mm space) for the wireframe backdrop
        self._drag = None                  # (kind, obj) currently being dragged
        self._dot_centers: list = []       # [(px, py, kind, obj)] for hit-testing
        self._scale = 1.0
        self._pad = 34
        self._cw = 600
        self._ch = 400
        self._h_min = 0.0
        self._v_min = 0.0
        self.off_x = tk.StringVar(value="0")
        self.off_y = tk.StringVar(value="0")
        self.off_z = tk.StringVar(value="0")
        self.scale_pct = tk.StringVar(value="100")
        self.tool_var = tk.StringVar(value="select")
        self.render_mode_var = tk.StringVar(value="solid")  # "solid" (shaded) or "wire"
        self._selected = None           # (kind, obj) currently highlighted
        self._measure_pts: list = []    # up to 2 measure points: (kind, obj, (x, y, z))
        self._item_rows: dict = {}      # item-list iid -> (kind, obj)
        self._model_version = 0          # bumped when the model preview changes
        self._rendered_tf = None         # transform signature the static layer was last drawn at

        root.title("ARsens — projectvoorbereiding")
        root.geometry("960x640")
        self._build_menu()
        self._build_body()
        self.refresh()

    # --- layout -----------------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Nieuw", command=self.new_project)
        m_file.add_command(label="Openen… (JSON / .arsenspkg)", command=self.open_any)
        m_file.add_command(label="Opslaan als JSON…", command=self.save_json)
        m_file.add_separator()
        m_file.add_command(label="Exporteer pakket (.arsenspkg)…", command=self.export_package)
        m_file.add_separator()
        m_file.add_command(label="Afsluiten", command=self.root.destroy)
        menubar.add_cascade(label="Bestand", menu=m_file)

        m_xlsx = tk.Menu(menubar, tearoff=0)
        m_xlsx.add_command(label="Importeer Excel…", command=self.import_excel)
        m_xlsx.add_command(label="Exporteer Excel…", command=self.export_excel)
        menubar.add_cascade(label="Excel", menu=m_xlsx)

        m_place = tk.Menu(menubar, tearoff=0)
        m_place.add_command(label="Sensor toevoegen…", command=self.add_sensor)
        m_place.add_command(label="Snelle sensor (+1 id)", command=self.quick_add_sensor)
        m_place.add_command(label="Tag toevoegen…", command=self.add_tag)
        menubar.add_cascade(label="Plaatsen", menu=m_place)

        m_tools = tk.Menu(menubar, tearoff=0)
        m_tools.add_command(label="3D-model koppelen…", command=self.attach_model)
        m_tools.add_command(label="Onderdelen (parts)…", command=self._parts_dialog)
        m_tools.add_command(label="Box op model maten", command=self._set_box_from_model)
        m_tools.add_separator()
        m_tools.add_command(label="Valideren", command=self.validate)
        menubar.add_cascade(label="Extra", menu=m_tools)

        self.root.config(menu=menubar)

    def _build_body(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Projectnaam").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.name_var, width=32)
        e.grid(row=0, column=1, sticky="w", padx=(6, 18))
        e.bind("<FocusOut>", lambda _e: self._pull_header())

        ttk.Label(top, text="Afmetingen mm (X/Y/Z)").grid(row=0, column=2, sticky="w")
        self.dim_x = tk.StringVar(); self.dim_y = tk.StringVar(); self.dim_z = tk.StringVar()
        for col, var in enumerate((self.dim_x, self.dim_y, self.dim_z)):
            de = ttk.Entry(top, textvariable=var, width=7)
            de.grid(row=0, column=3 + col, sticky="w", padx=2)
            de.bind("<FocusOut>", lambda _e: self._pull_header())

        self.model_var = tk.StringVar()
        ttk.Label(top, textvariable=self.model_var, foreground="#666").grid(
            row=1, column=0, columnspan=7, sticky="w", pady=(6, 0))

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.sensor_tree = self._make_table(nb, "Sensoren",
                                            ("order", "id", "name", "x_mm", "y_mm", "z_mm", "tol", "tag", "origin", "status"),
                                            self.add_sensor, self.edit_sensor, self.delete_sensor)
        self.tag_tree = self._make_table(nb, "Tags",
                                         ("id", "type", "size", "x_mm", "y_mm", "z_mm", "origin"),
                                         self.add_tag, self.edit_tag, self.delete_tag)
        self._make_plan_tab(nb)

        self.status = tk.StringVar(value="Klaar.")
        ttk.Label(self.root, textvariable=self.status, relief="sunken", anchor="w", padding=4).pack(fill="x")

    def _make_table(self, nb, title, columns, on_add, on_edit, on_delete) -> ttk.Treeview:
        frame = ttk.Frame(nb, padding=6)
        nb.add(frame, text=title)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        for c in columns:
            tree.heading(c, text=c)
            tree.column(c, width=84, anchor="center")
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        sb.pack(side="left", fill="y")
        tree.configure(yscrollcommand=sb.set)
        tree.bind("<Double-1>", lambda _e: on_edit())

        bar = ttk.Frame(frame, padding=(8, 0))
        bar.pack(side="left", fill="y")
        ttk.Button(bar, text="Toevoegen", command=on_add).pack(fill="x", pady=2)
        ttk.Button(bar, text="Bewerken", command=on_edit).pack(fill="x", pady=2)
        ttk.Button(bar, text="Verwijderen", command=on_delete).pack(fill="x", pady=2)
        return tree

    def _make_plan_tab(self, nb):
        frame = ttk.Frame(nb, padding=6)
        nb.add(frame, text="Plaatsing")

        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="Aanzicht:").pack(side="left")
        for label, value in (("Boven X/Y", "top"), ("Voor X/Z", "front"), ("Zij Y/Z", "side")):
            ttk.Radiobutton(bar, text=label, value=value, variable=self.view_var,
                            command=self._on_view_change).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(bar, text="Gereedschap:").pack(side="left")
        for label, value in (("Selecteer/sleep", "select"), ("Meten", "measure"),
                             ("Sensor +", "add_sensor"), ("Tag +", "add_tag")):
            ttk.Radiobutton(bar, text=label, value=value, variable=self.tool_var,
                            command=self._on_tool_change).pack(side="left", padx=2)

        mbar = ttk.Frame(frame)
        mbar.pack(fill="x", pady=(0, 4))
        ttk.Label(mbar, text="Model-offset mm:").pack(side="left")
        for var in (self.off_x, self.off_y, self.off_z):
            e = ttk.Entry(mbar, textvariable=var, width=7)
            e.pack(side="left", padx=2)
            e.bind("<Return>", lambda _e: self._apply_model_transform())
        ttk.Label(mbar, text="schaal %").pack(side="left", padx=(8, 2))
        se = ttk.Entry(mbar, textvariable=self.scale_pct, width=6)
        se.pack(side="left")
        se.bind("<Return>", lambda _e: self._apply_model_transform())
        ttk.Button(mbar, text="Toepassen", command=self._apply_model_transform).pack(side="left", padx=6)
        ttk.Button(mbar, text="Centreer in box", command=self._center_model_in_box).pack(side="left")
        ttk.Button(mbar, text="Box = model", command=self._set_box_from_model).pack(side="left", padx=6)
        ttk.Separator(mbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(mbar, text="Weergave:").pack(side="left")
        for label, value in (("Massief", "solid"), ("Draad", "wire")):
            ttk.Radiobutton(mbar, text=label, value=value, variable=self.render_mode_var,
                            command=self._full_redraw).pack(side="left", padx=2)

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, background="#0E1726", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._full_redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        side = ttk.Frame(body, width=250)
        side.pack(side="left", fill="y", padx=(6, 0))
        side.pack_propagate(False)
        ttk.Label(side, text="Sensoren & tags", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        self.item_tree = ttk.Treeview(side, columns=("kind", "id", "status"),
                                      show="headings", selectmode="browse", height=14)
        for col, head, w in (("kind", "Type", 50), ("id", "ID", 64), ("status", "Status", 122)):
            self.item_tree.heading(col, text=head)
            self.item_tree.column(col, width=w, anchor="w")
        self.item_tree.tag_configure("pending", foreground="#C9851F")
        self.item_tree.tag_configure("ok", foreground="#2F6FED")
        self.item_tree.tag_configure("fail", foreground="#D32F2F")
        self.item_tree.tag_configure("tagrow", foreground="#0E9C8C")
        self.item_tree.pack(fill="both", expand=True, pady=(2, 4))
        self.item_tree.bind("<<TreeviewSelect>>", self._on_item_select)
        self.item_tree.bind("<Double-1>", lambda _e: self._edit_selected_item())
        self.measure_var = tk.StringVar(value="")
        ttk.Label(side, textvariable=self.measure_var, foreground="#3a3f47",
                  wraplength=240, justify="left").pack(anchor="w")
        ttk.Button(side, text="Snelle sensor (+1 id)", command=self.quick_add_sensor).pack(fill="x", pady=(2, 0))
        bb = ttk.Frame(side)
        bb.pack(fill="x", pady=4)
        ttk.Button(bb, text="Bewerk", command=self._edit_selected_item).pack(side="left")
        ttk.Button(bb, text="Verwijder", command=self._delete_selected_item).pack(side="left", padx=4)

    # --- model <-> widgets ------------------------------------------------

    def _pull_header(self):
        self.project.project_name = self.name_var.get().strip() or "Nieuw project"
        try:
            self.project.dimensions_mm = MmPosition(
                int(float(self.dim_x.get() or 0)),
                int(float(self.dim_y.get() or 0)),
                int(float(self.dim_z.get() or 0)),
            )
        except ValueError:
            pass
        self._full_redraw()

    def refresh(self):
        self.name_var.set(self.project.project_name)
        d = self.project.dimensions_mm
        self.dim_x.set(str(d.x)); self.dim_y.set(str(d.y)); self.dim_z.set(str(d.z))
        models = ", ".join(m.file_name for m in self.project.stl_models) or "geen"
        self.model_var.set(f"3D-model(len): {models}")
        if self.project.stl_models:
            m0 = self.project.stl_models[0]
            self.off_x.set(str(m0.offset_mm.x))
            self.off_y.set(str(m0.offset_mm.y))
            self.off_z.set(str(m0.offset_mm.z))
            self.scale_pct.set(str(m0.scale_percent))

        self.sensor_tree.delete(*self.sensor_tree.get_children())
        for s in sorted(self.project.sensors, key=lambda s: s.order):
            self.sensor_tree.insert("", "end", values=(
                s.order, s.id, s.name, s.position_mm.x, s.position_mm.y, s.position_mm.z,
                s.tolerance_mm, "" if s.sensor_tag_id is None else s.sensor_tag_id,
                s.origin.value, s.status.value))

        self.tag_tree.delete(*self.tag_tree.get_children())
        for m in self.project.markers:
            self.tag_tree.insert("", "end", values=(
                m.id, m.type, m.size_mm, m.position_mm.x, m.position_mm.y, m.position_mm.z, m.origin.value))

        # Side list in the placement view (placed/placing overview).
        self.item_tree.delete(*self.item_tree.get_children())
        self._item_rows = {}
        for m in self.project.markers:
            iid = self.item_tree.insert("", "end", values=("Tag", m.id, m.origin.value), tags=("tagrow",))
            self._item_rows[iid] = ("tag", m)
        for s in sorted(self.project.sensors, key=lambda s: s.order):
            iid = self.item_tree.insert("", "end",
                                        values=("Sensor", s.id, f"{s.status.value} · {s.origin.value}"),
                                        tags=(s.status.value,))
            self._item_rows[iid] = ("sensor", s)
        if self._selected is not None:
            for iid, (_k, o) in self._item_rows.items():
                if o is self._selected[1]:
                    self.item_tree.selection_set(iid)
                    break

        self._full_redraw()

    def _selected_sensor(self) -> Sensor | None:
        sel = self.sensor_tree.selection()
        if not sel:
            return None
        sid = str(self.sensor_tree.item(sel[0], "values")[1])
        return next((s for s in self.project.sensors if s.id == sid), None)

    def _selected_tag(self) -> Marker | None:
        sel = self.tag_tree.selection()
        if not sel:
            return None
        tid = int(self.tag_tree.item(sel[0], "values")[0])
        return next((m for m in self.project.markers if m.id == tid), None)

    # --- sensor actions ---------------------------------------------------

    _SENSOR_FIELDS = [
        ("id", "Sensor-id", "str"), ("name", "Naam", "str"),
        ("x_mm", "X (mm)", "int"), ("y_mm", "Y (mm)", "int"), ("z_mm", "Z (mm)", "int"),
        ("tolerance_mm", "Tolerantie (mm)", "int"), ("instruction", "Instructie", "str"),
        ("sensor_tag_id", "Sensor-tag-id (optioneel)", "optint"),
        ("origin", "Herkomst", "choice", ["prepared", "on_the_fly"]),
        ("status", "Status", "choice", ["pending", "ok", "fail"]),
    ]

    def add_sensor(self):
        r = _FieldDialog(self.root, "Sensor toevoegen", self._SENSOR_FIELDS,
                         {"tolerance_mm": 50, "origin": "prepared", "status": "pending"}).result
        if not r:
            return
        order = (max((s.order for s in self.project.sensors), default=0)) + 1
        self.project.sensors.append(Sensor(
            order=order, id=r["id"] or str(order), name=r["name"],
            position_mm=MmPosition(r["x_mm"], r["y_mm"], r["z_mm"]),
            tolerance_mm=r["tolerance_mm"], instruction=r["instruction"],
            sensor_tag_id=r["sensor_tag_id"],
            origin=PlacementOrigin(r["origin"]), status=SensorStatus(r["status"])))
        self.status.set(f"Sensor '{r['id']}' toegevoegd."); self.refresh()

    def edit_sensor(self, sensor=None):
        s = sensor or self._selected_sensor()
        if not s:
            return
        init = {"id": s.id, "name": s.name, "x_mm": s.position_mm.x, "y_mm": s.position_mm.y,
                "z_mm": s.position_mm.z, "tolerance_mm": s.tolerance_mm, "instruction": s.instruction,
                "sensor_tag_id": "" if s.sensor_tag_id is None else s.sensor_tag_id,
                "origin": s.origin.value, "status": s.status.value}
        r = _FieldDialog(self.root, "Sensor bewerken", self._SENSOR_FIELDS, init).result
        if not r:
            return
        s.id = r["id"]; s.name = r["name"]
        s.position_mm = MmPosition(r["x_mm"], r["y_mm"], r["z_mm"])
        s.tolerance_mm = r["tolerance_mm"]; s.instruction = r["instruction"]
        s.sensor_tag_id = r["sensor_tag_id"]
        s.origin = PlacementOrigin(r["origin"]); s.status = SensorStatus(r["status"])
        self.status.set(f"Sensor '{s.id}' bijgewerkt."); self.refresh()

    def delete_sensor(self):
        s = self._selected_sensor()
        if s and messagebox.askyesno("Verwijderen", f"Sensor '{s.id}' verwijderen?"):
            self.project.sensors.remove(s)
            self.refresh()

    # --- tag actions ------------------------------------------------------

    _TAG_FIELDS = [
        ("id", "Tag-id", "int"), ("type", "Type", "str"), ("size_mm", "Formaat (mm)", "int"),
        ("x_mm", "X (mm)", "int"), ("y_mm", "Y (mm)", "int"), ("z_mm", "Z (mm)", "int"),
        ("rot_x", "Rotatie X", "float"), ("rot_y", "Rotatie Y", "float"), ("rot_z", "Rotatie Z", "float"),
        ("origin", "Herkomst", "choice", ["prepared", "on_the_fly"]),
    ]

    def add_tag(self):
        r = _FieldDialog(self.root, "Tag toevoegen", self._TAG_FIELDS,
                         {"type": "apriltag", "size_mm": 100, "origin": "prepared"}).result
        if not r:
            return
        self.project.markers.append(Marker(
            id=r["id"], type=r["type"] or "apriltag", size_mm=r["size_mm"],
            position_mm=MmPosition(r["x_mm"], r["y_mm"], r["z_mm"]),
            rotation_deg=FloatVector(r["rot_x"], r["rot_y"], r["rot_z"]),
            origin=PlacementOrigin(r["origin"])))
        self.status.set(f"Tag {r['id']} toegevoegd."); self.refresh()

    def edit_tag(self, marker=None):
        m = marker or self._selected_tag()
        if not m:
            return
        init = {"id": m.id, "type": m.type, "size_mm": m.size_mm, "x_mm": m.position_mm.x,
                "y_mm": m.position_mm.y, "z_mm": m.position_mm.z, "rot_x": m.rotation_deg.x,
                "rot_y": m.rotation_deg.y, "rot_z": m.rotation_deg.z, "origin": m.origin.value}
        r = _FieldDialog(self.root, "Tag bewerken", self._TAG_FIELDS, init).result
        if not r:
            return
        m.id = r["id"]; m.type = r["type"] or "apriltag"; m.size_mm = r["size_mm"]
        m.position_mm = MmPosition(r["x_mm"], r["y_mm"], r["z_mm"])
        m.rotation_deg = FloatVector(r["rot_x"], r["rot_y"], r["rot_z"])
        m.origin = PlacementOrigin(r["origin"])
        self.status.set(f"Tag {m.id} bijgewerkt."); self.refresh()

    def delete_tag(self):
        m = self._selected_tag()
        if m and messagebox.askyesno("Verwijderen", f"Tag {m.id} verwijderen?"):
            self.project.markers.remove(m)
            self.refresh()

    # --- file actions -----------------------------------------------------

    def new_project(self):
        self.project = Project(project_name="Nieuw project")
        self.model_sources.clear(); self.path = None
        self._rebuild_preview()
        self.status.set("Nieuw project."); self.refresh()

    def open_any(self):
        path = filedialog.askopenfilename(
            filetypes=[("ARsens", "*.arsenspkg *.json"), ("Pakket", "*.arsenspkg"), ("JSON", "*.json"), ("Alle", "*.*")])
        if not path:
            return
        try:
            if path.lower().endswith(".arsenspkg"):
                project, _manifest, models = pkg.read_package(path, extract_models_to=self._tmpdir.name)
                self.project = project
                self.model_sources = {fn: str(p) for fn, p in models.items()}
            else:
                self.project = pj.load_project(path)
                self.model_sources.clear()
            self.path = Path(path)
            self._rebuild_preview()
            self.status.set(f"Geopend: {path}")
            self.refresh()
        except Exception as exc:  # noqa: BLE001 - surface any load error to the user
            messagebox.showerror("Openen mislukt", str(exc))

    def save_json(self):
        self._pull_header()
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        pj.save_project(self.project, path)
        self.status.set(f"Opgeslagen: {path}")

    def import_excel(self):
        path = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            self.project = px.read_workbook(path)
            self._rebuild_preview()
            self.status.set(f"Excel geïmporteerd: {path}"); self.refresh()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Import mislukt", str(exc))

    def export_excel(self):
        self._pull_header()
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            px.write_workbook(self.project, path)
            self.status.set(f"Excel geëxporteerd: {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Export mislukt", str(exc))

    def attach_model(self):
        path = filedialog.askopenfilename(filetypes=[("3D-model", "*.stl *.obj *.ply"), ("Alle", "*.*")])
        if not path:
            return
        name = Path(path).name
        self.model_sources[name] = path
        if not any(m.file_name == name for m in self.project.stl_models):
            self.project.stl_models.append(StlModel(id=name, name=Path(path).stem, file_name=name))
        self.project.model_file = name
        before = len(self._preview_tris)
        self._rebuild_preview()
        if len(self._preview_tris) == before:
            if Path(path).suffix.lower() == ".ply":
                messagebox.showinfo("Model gekoppeld",
                                    "PLY-voorbeeld vereist numpy-stl; het model gaat wél mee in het pakket.")
            else:
                messagebox.showwarning("Model",
                                       f"Kon {name} niet als mesh lezen voor het voorbeeld "
                                       "(het gaat wél mee in het pakket).")
        else:
            self._center_model_in_box()   # drop the model onto the box so it's visible right away
        self.status.set(f"Model gekoppeld: {name}")
        self.refresh()

    def export_package(self):
        self._pull_header()
        path = filedialog.asksaveasfilename(defaultextension=".arsenspkg", filetypes=[("ARsens-pakket", "*.arsenspkg")])
        if not path:
            return
        missing = [m.file_name for m in self.project.stl_models if m.file_name not in self.model_sources]
        if missing:
            messagebox.showwarning("Model ontbreekt",
                                   "Geen bronbestand voor: " + ", ".join(missing) +
                                   ".\nKoppel het model opnieuw via Extra → 3D-model koppelen.")
        try:
            pkg.build_package(self.project, path, self.model_sources)
            self.status.set(f"Pakket geëxporteerd: {path}")
            messagebox.showinfo("Klaar", f"Pakket geschreven:\n{path}\n\nImporteer dit in de app.")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Export mislukt", str(exc))

    def validate(self):
        self._pull_header()
        issues = val.validate_project(self.project)
        if not issues:
            messagebox.showinfo("Validatie", "Geen problemen gevonden.")
        else:
            messagebox.showwarning("Validatie", "\n".join(issues))

    # --- interactive schematic -------------------------------------------

    _VIEWS = {"top": (0, 1), "front": (0, 2), "side": (1, 2)}   # axis indices: 0=X, 1=Y, 2=Z
    _AXIS_LABEL = ("X", "Y", "Z")
    _MAX_PREVIEW_TRIS = 3000

    def _axes(self):
        return self._VIEWS.get(self.view_var.get(), (0, 1))

    def _dim_along(self, axis: int) -> int:
        d = self.project.dimensions_mm
        return (d.x, d.y, d.z)[axis]

    def _rebuild_preview(self):
        """Read the attached model(s) and project their triangles into box-mm space (offset + scale
        applied, like the app). Pure STL/OBJ; capped so even big meshes stay snappy. Drawn once, not
        during drag. PLY/rotation are the numpy-stl path (v2)."""
        tris: list = []
        for model in self.project.stl_models:
            src = self.model_sources.get(model.file_name)
            if not src or not model.visible or Path(src).suffix.lower() not in (".stl", ".obj"):
                continue
            try:
                loaded = mesh.read_mesh(src, sample_to=self._MAX_PREVIEW_TRIS)
            except Exception:
                continue
            scale = (model.scale_percent or 100) / 100.0
            ox, oy, oz = model.offset_mm.x, model.offset_mm.y, model.offset_mm.z
            for t in loaded.triangles:
                tris.append(tuple((v[0] * scale + ox, v[1] * scale + oy, v[2] * scale + oz) for v in t))
        if len(tris) > self._MAX_PREVIEW_TRIS:
            step = len(tris) // self._MAX_PREVIEW_TRIS + 1
            tris = tris[::step]
        self._preview_tris = tris
        self._model_version += 1

    def _apply_model_transform(self):
        try:
            ox = int(float(self.off_x.get() or 0))
            oy = int(float(self.off_y.get() or 0))
            oz = int(float(self.off_z.get() or 0))
            pct = int(float(self.scale_pct.get() or 100))
        except ValueError:
            self.status.set("Model-offset en schaal moeten getallen zijn.")
            return
        for m in self.project.stl_models:
            m.offset_mm = MmPosition(ox, oy, oz)
            m.scale_percent = pct
        self._rebuild_preview()
        self._full_redraw()
        self.status.set(f"Model-offset ({ox}, {oy}, {oz}) mm · schaal {pct}%.")

    def _center_model_in_box(self):
        """Set the model offset so its bounding-box centre lands at the box centre (no rescale).
        Uses the current preview bounds (which already include the current offset)."""
        if not self._preview_tris:
            self.status.set("Geen leesbaar model om te centreren.")
            return
        verts = [v for t in self._preview_tris for v in t]
        cx = (min(v[0] for v in verts) + max(v[0] for v in verts)) / 2
        cy = (min(v[1] for v in verts) + max(v[1] for v in verts)) / 2
        cz = (min(v[2] for v in verts) + max(v[2] for v in verts)) / 2
        d = self.project.dimensions_mm
        cur = self.project.stl_models[0].offset_mm if self.project.stl_models else MmPosition(0, 0, 0)
        self.off_x.set(str(int(round(cur.x + d.x / 2 - cx))))
        self.off_y.set(str(int(round(cur.y + d.y / 2 - cy))))
        self.off_z.set(str(int(round(cur.z + d.z / 2 - cz))))
        self._apply_model_transform()

    def _set_box_from_model(self):
        """Size the box to the model bounding box and zero the offset so the model fills it."""
        mn = [None, None, None]
        mx = [None, None, None]
        for model in self.project.stl_models:
            src = self.model_sources.get(model.file_name)
            if not src or not model.visible or Path(src).suffix.lower() not in (".stl", ".obj"):
                continue
            try:
                loaded = mesh.read_mesh(src)
            except Exception:
                continue
            s = (model.scale_percent or 100) / 100.0
            for t in loaded.triangles:
                for v in t:
                    for a in range(3):
                        val = v[a] * s
                        mn[a] = val if mn[a] is None else min(mn[a], val)
                        mx[a] = val if mx[a] is None else max(mx[a], val)
        if mn[0] is None:
            self.status.set("Geen leesbaar model om de box op te maten.")
            return
        span = [max(1, int(round(mx[a] - mn[a]))) for a in range(3)]
        self.project.dimensions_mm = MmPosition(span[0], span[1], span[2])
        for model in self.project.stl_models:
            model.offset_mm = MmPosition(int(round(-mn[0])), int(round(-mn[1])), int(round(-mn[2])))
        self.dim_x.set(str(span[0]))
        self.dim_y.set(str(span[1]))
        self.dim_z.set(str(span[2]))
        self._rebuild_preview()
        self.refresh()
        self.status.set(f"Box op model gemaat: {span[0]} × {span[1]} × {span[2]} mm")

    def quick_add_sensor(self):
        """Add a sensor with the next free numeric id at the box centre — drag it into place."""
        order = max((s.order for s in self.project.sensors), default=0) + 1
        used = {s.id for s in self.project.sensors}
        nid = max((int(s.id) for s in self.project.sensors if s.id.isdigit()), default=0) + 1
        while str(nid) in used:
            nid += 1
        d = self.project.dimensions_mm
        sensor = Sensor(order=order, id=str(nid), name="sens",
                        position_mm=MmPosition(d.x // 2, d.y // 2, d.z // 2), tolerance_mm=50)
        self.project.sensors.append(sensor)
        self._selected = ("sensor", sensor)
        self.refresh()
        self.status.set(f"Snelle sensor {nid} toegevoegd (sleep hem op z'n plek).")

    def _parts_dialog(self):
        if not self.project.stl_models:
            messagebox.showinfo("Onderdelen", "Nog geen 3D-model gekoppeld (Extra → 3D-model koppelen).")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Onderdelen (parts)")
        dlg.transient(self.root)
        tree = ttk.Treeview(dlg, columns=("file", "vis"), show="headings", height=8, selectmode="browse")
        tree.heading("file", text="Bestand")
        tree.column("file", width=230)
        tree.heading("vis", text="Zichtbaar")
        tree.column("vis", width=80, anchor="center")
        tree.grid(row=0, column=0, columnspan=3, padx=10, pady=10)
        rows: dict = {}

        def reload():
            tree.delete(*tree.get_children())
            rows.clear()
            for m in self.project.stl_models:
                iid = tree.insert("", "end", values=(m.file_name, "ja" if m.visible else "nee"))
                rows[iid] = m

        def selected():
            s = tree.selection()
            return rows.get(s[0]) if s else None

        def toggle():
            m = selected()
            if m:
                m.visible = not m.visible
                self._rebuild_preview()
                self._full_redraw()
                reload()

        def remove():
            m = selected()
            if not m:
                return
            self.project.stl_models.remove(m)
            self.model_sources.pop(m.file_name, None)
            self._rebuild_preview()
            self.refresh()
            reload()

        ttk.Button(dlg, text="Zichtbaar aan/uit", command=toggle).grid(row=1, column=0, padx=6, pady=(0, 10))
        ttk.Button(dlg, text="Verwijderen", command=remove).grid(row=1, column=1, padx=6, pady=(0, 10))
        ttk.Button(dlg, text="Sluiten", command=dlg.destroy).grid(row=1, column=2, padx=6, pady=(0, 10))
        reload()

    def _recompute_transform(self):
        c = self.canvas
        self._cw = c.winfo_width() or 600
        self._ch = c.winfo_height() or 400
        h_ax, v_ax = self._axes()
        dh, dv = self._dim_along(h_ax) or 1, self._dim_along(v_ax) or 1
        # Fit the view to box + model + dots together (one shared mm-space) so the model is visible
        # wherever its coordinates sit relative to the box, and everything stays consistent.
        h_min, h_max, v_min, v_max = 0.0, float(dh), 0.0, float(dv)
        for t in self._preview_tris:
            for vtx in t:
                h_min = min(h_min, vtx[h_ax]); h_max = max(h_max, vtx[h_ax])
                v_min = min(v_min, vtx[v_ax]); v_max = max(v_max, vtx[v_ax])
        for obj in list(self.project.sensors) + list(self.project.markers):
            p = obj.position_mm.as_list()
            h_min = min(h_min, p[h_ax]); h_max = max(h_max, p[h_ax])
            v_min = min(v_min, p[v_ax]); v_max = max(v_max, p[v_ax])
        self._h_min, self._v_min = h_min, v_min
        span_h, span_v = (h_max - h_min) or 1, (v_max - v_min) or 1
        self._pad = 34
        self._scale = min((self._cw - 2 * self._pad) / span_h,
                          (self._ch - 2 * self._pad) / span_v) or 0.01

    def _to_px(self, h_mm, v_mm):
        return (self._pad + (h_mm - self._h_min) * self._scale,
                self._ch - self._pad - (v_mm - self._v_min) * self._scale)

    def _to_mm(self, px, py):
        return (self._h_min + (px - self._pad) / self._scale,
                self._v_min + (self._ch - self._pad - py) / self._scale)

    def _full_redraw(self):
        c = getattr(self, "canvas", None)
        if c is None:
            return
        h_ax, v_ax = self._axes()
        if self._dim_along(h_ax) <= 0 or self._dim_along(v_ax) <= 0:
            c.delete("all")
            c.create_text((c.winfo_width() or 600) / 2, (c.winfo_height() or 400) / 2,
                          text="Stel eerst de afmetingen in", fill="#88909c")
            self._rendered_tf = None
            return
        self._recompute_transform()
        # Re-render the (expensive) static layer only when the view/model/scale changes — not on
        # every sensor drag — so interaction stays smooth even with thousands of model triangles.
        tf = (round(self._scale, 5), round(self._h_min, 1), round(self._v_min, 1),
              self.view_var.get(), self._model_version, self.render_mode_var.get())
        if tf != self._rendered_tf:
            c.delete("static")
            self._render_static()
            self._rendered_tf = tf
        self._draw_dots()

    def _render_static(self):
        c = self.canvas
        h_ax, v_ax = self._axes()
        x0, y0 = self._to_px(0, 0)
        x1, y1 = self._to_px(self._dim_along(h_ax), self._dim_along(v_ax))
        c.create_rectangle(x0, y1, x1, y0, outline="#3a4759", width=1, tags="static")
        c.create_text((x0 + x1) / 2, y0 + 16, fill="#7d8696", tags="static",
                      text=f"{self._AXIS_LABEL[h_ax]} × {self._AXIS_LABEL[v_ax]} — "
                           f"{self._dim_along(h_ax)} × {self._dim_along(v_ax)} mm")
        tris = self._preview_tris
        if not tris:
            return
        if self.render_mode_var.get() == "wire":
            for t in tris:
                p0 = self._to_px(t[0][h_ax], t[0][v_ax])
                p1 = self._to_px(t[1][h_ax], t[1][v_ax])
                p2 = self._to_px(t[2][h_ax], t[2][v_ax])
                c.create_line(*p0, *p1, fill="#3a5170", tags="static")
                c.create_line(*p1, *p2, fill="#3a5170", tags="static")
                c.create_line(*p2, *p0, fill="#3a5170", tags="static")
            return
        # Solid: painter's depth sort (back-to-front) + flat shading, mirroring the app's rasterizer.
        depth_ax = ({0, 1, 2} - {h_ax, v_ax}).pop()
        lx, ly, lz = 0.35, -0.45, 0.82
        order = sorted(range(len(tris)),
                       key=lambda i: tris[i][0][depth_ax] + tris[i][1][depth_ax] + tris[i][2][depth_ax])
        for i in order:
            t = tris[i]
            nx, ny, nz = _tri_normal(t)
            shade = 0.30 + 0.70 * abs(nx * lx + ny * ly + nz * lz)
            col = _shade_hex(shade)
            p0 = self._to_px(t[0][h_ax], t[0][v_ax])
            p1 = self._to_px(t[1][h_ax], t[1][v_ax])
            p2 = self._to_px(t[2][h_ax], t[2][v_ax])
            c.create_polygon(p0[0], p0[1], p1[0], p1[1], p2[0], p2[1],
                             fill=col, outline=col, tags="static")

    def _draw_dots(self):
        c = self.canvas
        c.delete("dots")
        self._dot_centers = []
        h_ax, v_ax = self._axes()
        sel_obj = self._selected[1] if self._selected else None
        for m in self.project.markers:
            pos = m.position_mm.as_list()
            mx, my = self._to_px(pos[h_ax], pos[v_ax])
            if m is sel_obj:
                c.create_oval(mx - 9, my - 9, mx + 9, my + 9, outline="#ffffff", width=2, tags="dots")
            c.create_rectangle(mx - 5, my - 5, mx + 5, my + 5, fill=_TAG_COLOUR, outline="", tags="dots")
            c.create_text(mx, my - 12, text=str(m.id), fill=_TAG_COLOUR, font=("TkDefaultFont", 7), tags="dots")
            self._dot_centers.append((mx, my, "tag", m))
        for s in self.project.sensors:
            pos = s.position_mm.as_list()
            sx, sy = self._to_px(pos[h_ax], pos[v_ax])
            col = _STATUS_COLOUR.get(s.status, "#888")
            if s is sel_obj:
                c.create_oval(sx - 10, sy - 10, sx + 10, sy + 10, outline="#ffffff", width=2, tags="dots")
            c.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, fill=col, outline="white", tags="dots")
            c.create_text(sx, sy - 13, text=s.id, fill=col, font=("TkDefaultFont", 7), tags="dots")
            self._dot_centers.append((sx, sy, "sensor", s))
        if self._measure_pts:
            pts_px = []
            for (_k, _o, xyz) in self._measure_pts:
                mpx, mpy = self._to_px(xyz[h_ax], xyz[v_ax])
                pts_px.append((mpx, mpy))
                c.create_line(mpx - 6, mpy, mpx + 6, mpy, fill="#ffd166", width=2, tags="dots")
                c.create_line(mpx, mpy - 6, mpx, mpy + 6, fill="#ffd166", width=2, tags="dots")
            if len(pts_px) == 2:
                c.create_line(*pts_px[0], *pts_px[1], fill="#ffd166", width=2, dash=(4, 2), tags="dots")

    # --- hit-testing & selection -----------------------------------------

    def _hit_test(self, event):
        best, best_d = None, 16.0
        for (px, py, kind, obj) in self._dot_centers:
            d = ((px - event.x) ** 2 + (py - event.y) ** 2) ** 0.5
            if d <= best_d:
                best, best_d = (kind, obj), d
        return best

    def _iid_for(self, obj):
        for iid, (_k, o) in self._item_rows.items():
            if o is obj:
                return iid
        return None

    def _on_item_select(self, _event=None):
        sel = self.item_tree.selection()
        self._selected = self._item_rows.get(sel[0]) if sel else None
        self._draw_dots()
        if self._selected:
            kind, obj = self._selected
            p = obj.position_mm.as_list()
            label = f"Sensor {obj.id} · {obj.status.value}" if kind == "sensor" else f"Tag {obj.id}"
            self.status.set(f"{label} · {obj.origin.value} · XYZ {p} mm")

    def _edit_selected_item(self):
        if not self._selected:
            return
        kind, obj = self._selected
        self.edit_sensor(obj) if kind == "sensor" else self.edit_tag(obj)

    def _delete_selected_item(self):
        if not self._selected:
            return
        kind, obj = self._selected
        noun = "Sensor" if kind == "sensor" else "Tag"
        if not messagebox.askyesno("Verwijderen", f"{noun} {obj.id} verwijderen?"):
            return
        (self.project.sensors if kind == "sensor" else self.project.markers).remove(obj)
        self._selected = None
        self.refresh()

    # --- tool handlers ----------------------------------------------------

    def _on_view_change(self):
        self._measure_pts = []
        self._full_redraw()

    def _on_tool_change(self):
        self._measure_pts = []
        self.measure_var.set("")
        hints = {
            "select": "Klik om te selecteren, sleep om te verplaatsen.",
            "measure": "Meten: klik 2 punten (sensoren/tags snappen).",
            "add_sensor": "Klik in de box om een sensor te plaatsen.",
            "add_tag": "Klik in de box om een tag te plaatsen.",
        }
        self.status.set(hints.get(self.tool_var.get(), ""))
        cursor = "crosshair" if self.tool_var.get() in ("measure", "add_sensor", "add_tag") else ""
        try:
            self.canvas.configure(cursor=cursor)
        except tk.TclError:
            pass
        self._draw_dots()

    def _point_at(self, event):
        """A 3D measure point: snapped to a sensor/tag if near, else a free in-plane point (depth 0)."""
        hit = self._hit_test(event)
        if hit is not None:
            kind, obj = hit
            return (kind, obj, tuple(obj.position_mm.as_list()))
        h_ax, v_ax = self._axes()
        h_mm, v_mm = self._to_mm(event.x, event.y)
        coords = [0, 0, 0]
        coords[h_ax], coords[v_ax] = int(round(h_mm)), int(round(v_mm))
        return (None, None, tuple(coords))

    def _measure_click(self, event):
        if len(self._measure_pts) >= 2:
            self._measure_pts = []
        self._measure_pts.append(self._point_at(event))
        if len(self._measure_pts) == 1:
            self.measure_var.set("Meten: klik het 2e punt.")
        else:
            a, b = self._measure_pts[0][2], self._measure_pts[1][2]
            dx, dy, dz = abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2])
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            self.measure_var.set(f"Afstand {dist:.0f} mm\nΔX {dx} · ΔY {dy} · ΔZ {dz} mm")
            self.status.set(f"Meting: {dist:.0f} mm  (ΔX {dx}, ΔY {dy}, ΔZ {dz})")
        self._draw_dots()

    def _add_item_at(self, event, kind):
        h_ax, v_ax = self._axes()
        h_mm, v_mm = self._to_mm(event.x, event.y)
        h_mm = max(0, min(self._dim_along(h_ax), int(round(h_mm))))
        v_mm = max(0, min(self._dim_along(v_ax), int(round(v_mm))))
        depth_ax = ({0, 1, 2} - {h_ax, v_ax}).pop()
        coords = [0, 0, 0]
        coords[h_ax], coords[v_ax] = h_mm, v_mm
        coords[depth_ax] = int(self._dim_along(depth_ax) // 2)
        pos = MmPosition(coords[0], coords[1], coords[2])
        if kind == "sensor":
            order = max((s.order for s in self.project.sensors), default=0) + 1
            used = {s.id for s in self.project.sensors}
            sid = str(order)
            while sid in used:
                order += 1
                sid = str(order)
            self.project.sensors.append(Sensor(order=order, id=sid, name="sensor",
                                               position_mm=pos, tolerance_mm=50))
            self.status.set(f"Sensor {sid} geplaatst op {pos.as_list()} mm")
        else:
            tid = max((m.id for m in self.project.markers), default=0) + 1
            self.project.markers.append(Marker(id=tid, position_mm=pos))
            self.status.set(f"Tag {tid} geplaatst op {pos.as_list()} mm")
        self.refresh()

    def _on_press(self, event):
        tool = self.tool_var.get()
        if tool != "select":
            self._drag = None
            if tool == "measure":
                self._measure_click(event)
            elif tool == "add_sensor":
                self._add_item_at(event, "sensor")
            elif tool == "add_tag":
                self._add_item_at(event, "tag")
            return
        hit = self._hit_test(event)
        self._drag = hit
        self._selected = hit
        iid = self._iid_for(hit[1]) if hit else None
        if iid:
            self.item_tree.selection_set(iid)
            self.item_tree.see(iid)
        else:
            self.item_tree.selection_remove(*self.item_tree.selection())
        self._draw_dots()
        if hit:
            kind, obj = hit
            p = obj.position_mm.as_list()
            label = f"Sensor {obj.id} · {obj.status.value}" if kind == "sensor" else f"Tag {obj.id}"
            self.status.set(f"{label} · {obj.origin.value} · XYZ {p} mm")
        else:
            self.status.set("")

    def _on_drag(self, event):
        if self.tool_var.get() != "select" or not self._drag:
            return
        kind, obj = self._drag
        h_ax, v_ax = self._axes()
        h_mm, v_mm = self._to_mm(event.x, event.y)
        h_mm = max(0, min(self._dim_along(h_ax), int(round(h_mm))))
        v_mm = max(0, min(self._dim_along(v_ax), int(round(v_mm))))
        coords = obj.position_mm.as_list()
        coords[h_ax], coords[v_ax] = h_mm, v_mm
        obj.position_mm = MmPosition(coords[0], coords[1], coords[2])
        self._draw_dots()
        who = obj.id if kind == "sensor" else f"tag {obj.id}"
        self.status.set(f"{who}: {self._AXIS_LABEL[h_ax]}={h_mm}, {self._AXIS_LABEL[v_ax]}={v_mm} mm")

    def _on_release(self, _event):
        if self.tool_var.get() == "select" and self._drag:
            self._drag = None
            self.refresh()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    AuthoringApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
