"""Project validation rules (per spec). Pure — no UI. Returns a list of Issues."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import geometry as geo
from .models import Project


@dataclass
class Issue:
    level: str   # "error" or "warning"
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.message}"


def _has_bad_number(values) -> bool:
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return True
        if math.isnan(f) or math.isinf(f):
            return True
    return False


def validate_project(project: Project, models_dir: Optional[Path] = None,
                     model_bounds: Optional[dict] = None) -> list[Issue]:
    """Validate a project. ``models_dir`` (optional) checks model files exist; ``model_bounds`` maps
    file_name -> (size_x, size_y, size_z) mm to warn on big bbox/dimension mismatches."""
    issues: list[Issue] = []
    dims = project.dimensions_mm

    if len(dims) != 3 or any(d <= 0 for d in dims):
        issues.append(Issue("error", f"Project dimensions must be > 0 (got {dims})."))

    # Sensors
    seen_sensor: set[str] = set()
    for s in project.sensors:
        if s.id in seen_sensor:
            issues.append(Issue("error", f"Duplicate sensor id '{s.id}'."))
        seen_sensor.add(s.id)
        if _has_bad_number(s.position_mm):
            issues.append(Issue("error", f"Sensor '{s.id}' has NaN/None coordinates."))
        elif not geo.point_inside_box(s.position_mm, dims):
            issues.append(Issue("warning", f"Sensor '{s.id}' lies outside the box ({s.position_mm})."))
        if s.tolerance_mm <= 0:
            issues.append(Issue("error", f"Sensor '{s.id}' tolerance must be > 0."))
        if s.reference_tag_id is not None:
            tag = next((m for m in project.markers if m.id == s.reference_tag_id), None)
            if tag is None:
                issues.append(Issue("error", f"Sensor '{s.id}' references tag {s.reference_tag_id} which does not exist."))
            elif not tag.active:
                issues.append(Issue("warning", f"Sensor '{s.id}' references tag {s.reference_tag_id} which is inactive."))

    # Tags
    seen_tag: set[int] = set()
    for m in project.markers:
        if m.id in seen_tag:
            issues.append(Issue("error", f"Duplicate tag id {m.id}."))
        seen_tag.add(m.id)
        if m.size_mm <= 0:
            issues.append(Issue("error", f"Tag {m.id} size must be > 0."))
        if _has_bad_number(m.position_mm):
            issues.append(Issue("error", f"Tag {m.id} has NaN/None coordinates."))
            continue
        plane = geo.plane_of_point(m.position_mm, dims, tol=1.0)
        if plane is None:
            issues.append(Issue("error", f"Tag {m.id} does not lie exactly on a plane (Front/Back/Left/Right/Top)."))
        else:
            u, v = geo.tag_uv_of_point(plane, m.position_mm)
            u_max, v_max = geo.plane_uv_extent(plane, dims)
            half = m.size_mm / 2.0
            if not (-1.0 <= u <= u_max + 1.0 and -1.0 <= v <= v_max + 1.0):
                issues.append(Issue("warning", f"Tag {m.id} center is outside the {plane.value} rectangle."))
            elif u < half or v < half or u > u_max - half or v > v_max - half:
                issues.append(Issue("warning", f"Tag {m.id} extends past the edge of the {plane.value} plane."))

    # Models
    for sm in project.stl_models:
        if sm.scale_percent <= 0:
            issues.append(Issue("error", f"Model '{sm.id}' scale_percent must be > 0."))
        if not sm.file_name:
            issues.append(Issue("error", f"Model '{sm.id}' has no file_name."))
        elif models_dir is not None and not (Path(models_dir) / sm.file_name).exists():
            issues.append(Issue("error", f"Model file '{sm.file_name}' not found in models/."))
        if model_bounds and sm.file_name in model_bounds:
            bx, by, bz = model_bounds[sm.file_name]
            scaled = [bx * sm.scale_percent / 100.0, by * sm.scale_percent / 100.0, bz * sm.scale_percent / 100.0]
            for axis, (b, d) in enumerate(zip(scaled, dims)):
                if d > 0 and (b > 1.5 * d or b < 0.5 * d):
                    issues.append(Issue("warning",
                                        f"Model '{sm.id}' bounding box on axis {axis} ({b:.0f} mm) differs strongly "
                                        f"from project dimension ({d} mm)."))
                    break

    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)
