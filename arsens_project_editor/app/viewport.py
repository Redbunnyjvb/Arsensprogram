"""PyVista 3D scene: transformer box, models (transformed), tags as plane squares, sensors as
pins + normals, axes and plane labels. Works with any PyVista plotter (QtInteractor or off-screen).

Rendering is batched (``suppress_rendering``) so a rebuild swaps in one frame instead of flashing,
and selection / measure / pick-plane overlays update *incrementally* (add/remove their own actors)
so interacting never rebuilds the whole scene."""
from __future__ import annotations

import numpy as np
import pyvista as pv

from . import geometry as geo
from .models import Project, SensorStatus

# Default status palette — vivid and distinct from the model role palette below. Editable at runtime
# via [TransformerScene.status_colors] (the "Sensor colours" swatches in the Tools panel).
_STATUS_COLOR = {
    SensorStatus.PENDING: "#FFC107",  # amber
    SensorStatus.OK: "#2DD4BF",       # teal-green
    SensorStatus.FAIL: "#FF4D6D",     # pink-red
}
# A distinct colour per assembly role so tank/cover/core/… are tellable apart at a glance.
_ROLE_COLOR = {
    "TANK": "#8E9CB6",
    "COVER": "#E0A04A",
    "CORE": "#3FB6A8",
    "ACTIVE_PART": "#A78BFA",
    "WIKSETS": "#C9772E",
    "BUSHINGS_TURRETS": "#7FB069",
    "OTHER": "#8892A6",
}
_TAG_COLOR = "#13E3CE"
_BOX_COLOR = "#5A6678"
_ORIENT_LABEL_COLOR = "#7FD4FF"  # bright cyan orientation labels
_SENSOR_LABEL_COLOR = "#EAF1FF"
_SELECT_COLOR = "#FFFFFF"        # halo around the currently selected marker
_MEASURE_COLOR = "#FFE14D"       # measure line / legs / label


class TransformerScene:
    def __init__(self, plotter):
        self.plotter = plotter
        self.project: Project | None = None
        self.meshes: dict[str, pv.PolyData] = {}  # file_name -> raw mesh (model-space)
        self.show_orientation_labels = True  # toolbar "Labels" toggle drives this
        self.status_colors = dict(_STATUS_COLOR)  # editable sensor-status palette
        # Currently selected marker ("sensor"|"tag", id) — drawn with a halo.
        self.selected: tuple[str, object] | None = None
        # Active measurement (p1, p2, drop_axis) — diagonal + right-angle legs + label.
        self.measure: tuple | None = None
        # Per-item actor handles [(actor, base_center), …] so a drag moves just those actors cheaply
        # via actor.SetPosition instead of rebuilding the whole scene each mouse-move.
        self.sensor_actors: dict[object, list] = {}
        self.tag_actors: dict[object, list] = {}
        # Incremental-overlay actor handles (added/removed without a full redraw).
        self._sel_actors: list = []
        self._meas_actors: list = []
        self._pick_plane_name = None       # geo.TagPlane locked for 2D editing, or None
        self._pick_plane_actor = None
        self._preview_actor = None         # ghost marker following the cursor while placing
        self._camera_ready = False  # first draw fits; later draws keep the user's camera
        self.bg_color = "#FFFFFF"   # default white (user request); changeable in the Tools panel
        self.ink = "#1B2430"        # box/label colour, auto-contrasted to the background
        self._apply_background()

    def set_project(self, project: Project) -> None:
        self.project = project

    def set_mesh(self, file_name: str, pv_mesh) -> None:
        self.meshes[file_name] = pv_mesh

    def remove_mesh(self, file_name: str) -> None:
        self.meshes.pop(file_name, None)

    def _apply_background(self) -> None:
        """Set the viewport background and pick a contrasting 'ink' for the box + labels."""
        try:
            self.plotter.set_background(self.bg_color)
        except Exception:
            pass
        self.ink = "#1B2430" if geo.is_light_color(self.bg_color) else "#DCE6F5"

    def set_background_color(self, hex_color: str) -> None:
        self.bg_color = hex_color
        self._apply_background()
        self.redraw()

    def _pin_radius(self) -> float:
        if self.project is None:
            return 12.0
        dims = [float(d) for d in self.project.dimensions_mm]
        return float(np.clip(min(dims) * 0.01, 8.0, 35.0)) if min(dims) > 0 else 12.0

    def redraw(self, reset_camera: bool = False) -> None:
        """Full structural rebuild. Batched into one frame (no flash) via suppress_rendering."""
        p = self.plotter
        prev_cam = None
        try:
            prev_cam = p.camera_position
        except Exception:
            prev_cam = None
        try:
            p.suppress_rendering = True
        except Exception:
            pass
        try:
            p.clear()
            self.sensor_actors = {}
            self.tag_actors = {}
            self._sel_actors = []
            self._meas_actors = []
            self._pick_plane_actor = None
            self._preview_actor = None
            if self.project is None:
                return
            try:
                p.enable_lightkit()
            except Exception:
                pass
            proj = self.project
            dims = [float(d) for d in proj.dimensions_mm]
            dx, dy, dz = dims

            p.add_mesh(pv.Box(bounds=(0, dx, 0, dy, 0, dz)), style="wireframe",
                       color=self.ink, line_width=1)

            for model in proj.stl_models:
                mesh = self.meshes.get(model.file_name)
                if mesh is None or not model.visible:
                    continue
                center = np.asarray(mesh.center, dtype=float)
                pts = geo.transform_points(mesh.points, center, model.scale_percent,
                                           model.rotation_deg, model.offset_mm)
                shown = mesh.copy()
                shown.points = pts
                try:
                    shown.compute_normals(cell_normals=False, point_normals=True, inplace=True)
                except Exception:
                    pass
                color = _ROLE_COLOR.get(str(model.role).upper(), _ROLE_COLOR["OTHER"])
                p.add_mesh(shown, color=color, smooth_shading=True,
                           specular=0.4, specular_power=15, ambient=0.22, diffuse=0.78)

            tag_label_pts: list = []
            tag_label_txt: list = []
            for tag in proj.markers:
                plane = geo.plane_of_point(tag.position_mm, dims, tol=2.0)
                normal = geo.plane_outward_normal(plane) if plane else np.array([0.0, 0.0, 1.0])
                center = np.asarray(tag.position_mm, dtype=float)
                square = pv.Plane(center=center, direction=normal,
                                  i_size=max(1, tag.size_mm), j_size=max(1, tag.size_mm))
                actor = p.add_mesh(square, color=_TAG_COLOR, opacity=0.95, lighting=False,
                                   show_edges=True, edge_color=self.ink, line_width=2)
                self.tag_actors[tag.id] = [(actor, center.copy())]
                tag_label_pts.append(center + normal * (tag.size_mm * 0.6 + 1.0))
                tag_label_txt.append(f"#{tag.id}")

            pin_r = self._pin_radius()
            sensor_label_pts: list = []
            sensor_label_txt: list = []
            for sensor in proj.sensors:
                pos = np.asarray(sensor.position_mm, dtype=float)
                color = self.status_colors.get(sensor.status, "#888888")
                handles: list = []
                handles.append((p.add_mesh(pv.Sphere(radius=pin_r, center=pos), color=color,
                                           lighting=False), pos.copy()))
                n = np.asarray(sensor.normal, dtype=float)
                if float(np.linalg.norm(n)) > 1e-6:
                    handles.append((p.add_mesh(pv.Arrow(start=pos, direction=n, scale=pin_r * 2.5),
                                               color=color, lighting=False), pos.copy()))
                self.sensor_actors[sensor.id] = handles
                sensor_label_pts.append(pos + np.array([0.0, 0.0, pin_r * 1.8]))
                sensor_label_txt.append(sensor.id)

            # Overlays that must survive a structural rebuild.
            self._sel_actors = self._build_selection_actors(pin_r)
            self._meas_actors = self._build_measure_actors()
            if self._pick_plane_name is not None:
                self._pick_plane_actor = self._build_pick_plane_actor(self._pick_plane_name)

            if self.show_orientation_labels:
                labels = [
                    (dx / 2, 0, dz / 2, "Front"), (dx / 2, dy, dz / 2, "Back"),
                    (0, dy / 2, dz / 2, "Left"), (dx, dy / 2, dz / 2, "Right"),
                    (dx / 2, dy / 2, dz, "Top"),
                ]
                try:
                    pts = np.array([[a, b, c] for a, b, c, _ in labels], dtype=float)
                    p.add_point_labels(pts, [t for *_, t in labels], font_size=14, bold=True,
                                       text_color=self.ink, shape=None, always_visible=True)
                except Exception:
                    pass
            if sensor_label_pts:
                try:
                    p.add_point_labels(np.asarray(sensor_label_pts, dtype=float), sensor_label_txt,
                                       font_size=12, bold=True, text_color=self.ink,
                                       shape=None, always_visible=True)
                except Exception:
                    pass
            if tag_label_pts:
                try:
                    p.add_point_labels(np.asarray(tag_label_pts, dtype=float), tag_label_txt,
                                       font_size=12, bold=True, text_color=self.ink,
                                       shape=None, always_visible=True)
                except Exception:
                    pass
            try:
                p.add_axes()
            except Exception:
                pass
            try:
                p.enable_eye_dome_lighting()
            except Exception:
                pass
            if reset_camera or not self._camera_ready:
                try:
                    p.reset_camera()
                    self._camera_ready = True
                except Exception:
                    pass
            elif prev_cam is not None:
                try:
                    p.camera_position = prev_cam
                except Exception:
                    pass
        finally:
            try:
                p.suppress_rendering = False
            except Exception:
                pass
            try:
                p.render()
            except Exception:
                pass

    # --- incremental overlays (no full rebuild) ---------------------------

    def _build_selection_actors(self, pin_r: float) -> list:
        actors: list = []
        if self.selected is None or self.project is None:
            return actors
        kind, ident = self.selected
        try:
            if kind == "sensor":
                s = next((x for x in self.project.sensors if x.id == ident), None)
                if s is not None:
                    actors.append(self.plotter.add_mesh(
                        pv.Sphere(radius=pin_r * 1.7, center=np.asarray(s.position_mm, dtype=float)),
                        color=self.ink, style="wireframe", line_width=2, lighting=False, render=False))
            elif kind == "tag":
                m = next((x for x in self.project.markers if x.id == ident), None)
                if m is not None:
                    dims = [float(d) for d in self.project.dimensions_mm]
                    plane = geo.plane_of_point(m.position_mm, dims, tol=2.0)
                    normal = geo.plane_outward_normal(plane) if plane else np.array([0.0, 0.0, 1.0])
                    big = max(1, int(m.size_mm * 1.35))
                    actors.append(self.plotter.add_mesh(
                        pv.Plane(center=np.asarray(m.position_mm, dtype=float), direction=normal,
                                 i_size=big, j_size=big),
                        color=self.ink, style="wireframe", line_width=2, lighting=False, render=False))
        except Exception:
            pass
        return actors

    def set_selection(self, kind, ident) -> None:
        self.selected = (kind, ident) if kind is not None else None
        self._remove_actors(self._sel_actors)
        self._sel_actors = self._build_selection_actors(self._pin_radius())
        self._render()

    def clear_selection(self) -> None:
        self.set_selection(None, None)

    def _build_measure_actors(self) -> list:
        actors: list = []
        if not self.measure:
            return actors
        try:
            p1, p2, drop = self.measure
            p1 = np.asarray(p1, dtype=float)
            p2 = np.asarray(p2, dtype=float)
            d_a, d_b, diag, (axis_a, axis_b) = geo.inplane_deltas(p1, p2, drop)
            corner = p1.copy()
            corner[axis_a] = p2[axis_a]
            actors.append(self.plotter.add_mesh(pv.Line(p1, p2), color=_MEASURE_COLOR, line_width=3, render=False))
            actors.append(self.plotter.add_mesh(pv.Line(p1, corner), color=_MEASURE_COLOR, line_width=2, render=False))
            actors.append(self.plotter.add_mesh(pv.Line(corner, p2), color=_MEASURE_COLOR, line_width=2, render=False))
            letters = ["X", "Y", "Z"]
            text = f"Δ{letters[axis_a]} {d_a:.0f} · Δ{letters[axis_b]} {d_b:.0f} · d {diag:.0f} mm"
            actors.append(self.plotter.add_point_labels(
                np.asarray([(p1 + p2) / 2.0], dtype=float), [text], font_size=13, bold=True,
                text_color=_MEASURE_COLOR, shape=None, always_visible=True, render=False))
        except Exception:
            pass
        return actors

    def set_measure(self, p1, p2, drop_axis) -> None:
        self.measure = (p1, p2, drop_axis)
        self._remove_actors(self._meas_actors)
        self._meas_actors = self._build_measure_actors()
        self._render()

    def clear_measure(self) -> None:
        self.measure = None
        self._remove_actors(self._meas_actors)
        self._meas_actors = []
        self._render()

    def _build_pick_plane_actor(self, plane):
        if self.project is None or plane is None:
            return None
        try:
            dims = [float(d) for d in self.project.dimensions_mm]
            u_ax, v_ax = geo.plane_uv_axes(plane)
            u_max, v_max = geo.plane_uv_extent(plane, dims)
            axis, value = geo.plane_fixed_axis(plane, dims)
            normal = geo.plane_outward_normal(plane)
            center = u_ax * (u_max / 2.0) + v_ax * (v_max / 2.0)
            center[axis] = value
            center = center - normal * 2.0  # sit just behind the markers so they pick first
            return self.plotter.add_mesh(
                pv.Plane(center=center, direction=normal, i_size=max(1.0, u_max), j_size=max(1.0, v_max)),
                color="#16223A", opacity=0.06, lighting=False, pickable=True, render=False)
        except Exception:
            return None

    def set_pick_plane(self, plane) -> None:
        """Add (or replace) a near-transparent full-face plane on [plane] so click-placement and
        drag-picking have a surface to hit even off the model. ``plane=None`` removes it."""
        self._pick_plane_name = plane
        if self._pick_plane_actor is not None:
            self._remove_actors([self._pick_plane_actor])
            self._pick_plane_actor = None
        if plane is not None:
            self._pick_plane_actor = self._build_pick_plane_actor(plane)
        self._render()

    def clear_pick_plane(self) -> None:
        self.set_pick_plane(None)

    def set_preview(self, point, color) -> None:
        """Show/update a translucent ghost marker at ``point`` (cursor preview while placing)."""
        if self._preview_actor is not None:
            self._remove_actors([self._preview_actor])
            self._preview_actor = None
        try:
            self._preview_actor = self.plotter.add_mesh(
                pv.Sphere(radius=self._pin_radius(), center=np.asarray(point, dtype=float)),
                color=color, opacity=0.45, lighting=False, render=False)
        except Exception:
            self._preview_actor = None
        self._render()

    def clear_preview(self) -> None:
        if self._preview_actor is not None:
            self._remove_actors([self._preview_actor])
            self._preview_actor = None
            self._render()

    def translate_item(self, kind: str, ident, new_center) -> None:
        """Cheaply move a marker's actors to ``new_center`` during a drag (no full rebuild)."""
        handles = (self.sensor_actors if kind == "sensor" else self.tag_actors).get(ident)
        if not handles:
            return
        new = np.asarray(new_center, dtype=float)
        for actor, base in handles:
            d = new - np.asarray(base, dtype=float)
            try:
                actor.SetPosition(float(d[0]), float(d[1]), float(d[2]))
            except Exception:
                pass
        self._render()

    def _remove_actors(self, actors) -> None:
        for a in actors or []:
            try:
                self.plotter.remove_actor(a, render=False)
            except Exception:
                pass

    def _render(self) -> None:
        try:
            self.plotter.render()
        except Exception:
            pass

    def view(self, preset: str) -> None:
        p = self.plotter
        try:
            if preset == "top":
                p.view_xy()
            elif preset == "front":
                p.view_xz()
            elif preset == "back":
                p.view_xz(); p.camera.azimuth = p.camera.azimuth + 180
            elif preset == "left":
                p.view_yz(); p.camera.azimuth = p.camera.azimuth + 180  # camera to -X = left side
            elif preset == "right":
                p.view_yz()  # camera at +X = right side
            else:
                p.view_isometric()
            p.reset_camera()
        except Exception:
            pass
