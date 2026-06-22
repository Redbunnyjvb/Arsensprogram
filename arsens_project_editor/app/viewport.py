"""PyVista 3D scene: transformer box, models (transformed), tags as plane squares, sensors as
pins + normals, axes and plane labels. Works with any PyVista plotter (QtInteractor or off-screen)."""
from __future__ import annotations

import numpy as np
import pyvista as pv

from . import geometry as geo
from .models import Project, SensorStatus

_STATUS_COLOR = {
    SensorStatus.PENDING: "#F5B544",
    SensorStatus.OK: "#2F6FED",
    SensorStatus.FAIL: "#E0573B",
}
_MODEL_COLOR = "#8E9CB6"
_TAG_COLOR = "#19C3B2"
_BOX_COLOR = "#5A6678"


class TransformerScene:
    def __init__(self, plotter):
        self.plotter = plotter
        self.project: Project | None = None
        self.meshes: dict[str, pv.PolyData] = {}  # file_name -> raw mesh (model-space)
        try:
            self.plotter.set_background("#0E1726")
        except Exception:
            pass

    def set_project(self, project: Project) -> None:
        self.project = project

    def set_mesh(self, file_name: str, pv_mesh) -> None:
        self.meshes[file_name] = pv_mesh

    def remove_mesh(self, file_name: str) -> None:
        self.meshes.pop(file_name, None)

    def redraw(self) -> None:
        p = self.plotter
        p.clear()
        if self.project is None:
            return
        # A multi-light rig instead of the flat default headlight, so surface relief is shaded.
        try:
            p.enable_lightkit()
        except Exception:
            pass
        proj = self.project
        dims = [float(d) for d in proj.dimensions_mm]
        dx, dy, dz = dims

        p.add_mesh(pv.Box(bounds=(0, dx, 0, dy, 0, dz)), style="wireframe",
                   color=_BOX_COLOR, line_width=1)

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
                # Recompute normals on the transformed surface so lighting is correct.
                shown.compute_normals(cell_normals=False, point_normals=True, inplace=True)
            except Exception:
                pass
            p.add_mesh(shown, color=_MODEL_COLOR, smooth_shading=True,
                       specular=0.4, specular_power=15, ambient=0.22, diffuse=0.78)

        for tag in proj.markers:
            plane = geo.plane_of_point(tag.position_mm, dims, tol=2.0)
            normal = geo.plane_outward_normal(plane) if plane else np.array([0.0, 0.0, 1.0])
            square = pv.Plane(center=np.asarray(tag.position_mm, dtype=float), direction=normal,
                              i_size=max(1, tag.size_mm), j_size=max(1, tag.size_mm))
            p.add_mesh(square, color=_TAG_COLOR, opacity=0.92)

        pin_r = max(20.0, min(dims) / 60.0) if min(dims) > 0 else 20.0
        for sensor in proj.sensors:
            pos = np.asarray(sensor.position_mm, dtype=float)
            color = _STATUS_COLOR.get(sensor.status, "#888888")
            p.add_mesh(pv.Sphere(radius=pin_r, center=pos), color=color)
            n = np.asarray(sensor.normal, dtype=float)
            if float(np.linalg.norm(n)) > 1e-6:
                p.add_mesh(pv.Arrow(start=pos, direction=n, scale=pin_r * 4), color=color)

        labels = [
            (dx / 2, 0, dz / 2, "Front"), (dx / 2, dy, dz / 2, "Back"),
            (0, dy / 2, dz / 2, "Left"), (dx, dy / 2, dz / 2, "Right"),
            (dx / 2, dy / 2, dz, "Top"),
        ]
        try:
            pts = np.array([[a, b, c] for a, b, c, _ in labels], dtype=float)
            p.add_point_labels(pts, [t for *_, t in labels], font_size=11,
                               text_color="#9aa6b6", shape=None, always_visible=True)
        except Exception:
            pass
        try:
            p.add_axes()
        except Exception:
            pass
        # Eye-dome lighting darkens depth discontinuities -> raised/recessed features become visible.
        try:
            p.enable_eye_dome_lighting()
        except Exception:
            pass
        try:
            p.reset_camera()
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
                p.view_yz()
            elif preset == "right":
                p.view_yz(); p.camera.azimuth = p.camera.azimuth + 180
            else:
                p.view_isometric()
            p.reset_camera()
        except Exception:
            pass
