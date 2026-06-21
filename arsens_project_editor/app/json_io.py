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
    d = dict(data)
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
