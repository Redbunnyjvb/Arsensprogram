"""Project JSON <-> pydantic models, in the ARsens app's wire format.

Mirrors JsonProjectStore.kt key-for-key. Legacy projects without ``origin`` derive it the same way
the app does (sensor: placement present => on_the_fly, else prepared; marker: prepared).
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Project


def project_to_dict(project: Project) -> dict:
    # exclude_none drops optional keys (reference_tag_id, placement, ...) when absent, like the app.
    return project.model_dump(mode="json", exclude_none=True)


def project_from_dict(data: dict) -> Project:
    if not isinstance(data, dict):
        raise ValueError("ARsens JSON root must be an object.")

    # Accept both:
    #   1) a plain project JSON: {"project_name": ..., "sensors": ...}
    #   2) an ARsens report/export envelope:
    #      {"exported_at": ..., "project": {...}, "installation_log": ...}
    if isinstance(data.get("project"), dict):
        d = dict(data["project"])
    else:
        d = dict(data)

    # Do not silently turn an unrelated/wrong JSON file into a blank default project.
    recognised = {"project_name", "dimensions_mm", "coordinate_frame",
                  "sensors", "markers", "stl_models"}
    if not any(key in d for key in recognised):
        raise ValueError(
            "This JSON file does not contain a recognizable ARsens project. "
            "Expected project fields at the root or inside a 'project' object."
        )

    sensors = []
    for s in d.get("sensors", []):
        s = dict(s)
        if "origin" not in s or not s.get("origin"):
            s["origin"] = "on_the_fly" if isinstance(s.get("placement"), dict) else "prepared"
        sensors.append(s)
    d["sensors"] = sorted(sensors, key=lambda s: s.get("order", 0))
    markers = []
    for m in d.get("markers", []):
        m = dict(m)
        m.setdefault("origin", "prepared")
        markers.append(m)
    d["markers"] = markers
    return Project.model_validate(d)


def project_to_json(project: Project, indent: int = 2) -> str:
    return json.dumps(project_to_dict(project), indent=indent, ensure_ascii=False)


def project_from_json(text: str) -> Project:
    return project_from_dict(json.loads(text))


def load_project(path) -> Project:
    return project_from_json(Path(path).read_text(encoding="utf-8"))


def save_project(project: Project, path) -> None:
    Path(path).write_text(project_to_json(project), encoding="utf-8")
