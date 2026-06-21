"""Domain rules — pure, no I/O. Returns human-readable issues; does not raise."""
from __future__ import annotations

from .model import MmPosition, Project


def _inside_box(pos: MmPosition, dims: MmPosition) -> bool:
    return 0 <= pos.x <= dims.x and 0 <= pos.y <= dims.y and 0 <= pos.z <= dims.z


def validate_project(p: Project) -> list[str]:
    issues: list[str] = []
    dims = p.dimensions_mm

    seen_sensor: set[str] = set()
    for s in p.sensors:
        if s.id in seen_sensor:
            issues.append(f"Dubbele sensor-id '{s.id}'.")
        seen_sensor.add(s.id)
        if not s.id:
            issues.append("Sensor zonder id.")
        if s.tolerance_mm <= 0:
            issues.append(f"Sensor '{s.id}': tolerantie moet groter dan 0 zijn.")
        if not _inside_box(s.position_mm, dims):
            issues.append(f"Sensor '{s.id}' valt buiten de box {dims.as_list()} (XYZ {s.position_mm.as_list()}).")

    seen_tag: set[int] = set()
    for m in p.markers:
        if m.id in seen_tag:
            issues.append(f"Dubbele tag-id {m.id}.")
        seen_tag.add(m.id)
        if m.size_mm <= 0:
            issues.append(f"Tag {m.id}: formaat moet groter dan 0 zijn.")
        if not _inside_box(m.position_mm, dims):
            issues.append(f"Tag {m.id} valt buiten de box (XYZ {m.position_mm.as_list()}).")

    # Sensor-tag verwijzingen moeten naar een bestaande tag wijzen (waarschuwing, niet fataal).
    tag_ids = {m.id for m in p.markers}
    for s in p.sensors:
        if s.sensor_tag_id is not None and s.sensor_tag_id not in tag_ids:
            issues.append(f"Sensor '{s.id}' verwijst naar sensor-tag {s.sensor_tag_id} die niet in het project staat.")

    return issues
