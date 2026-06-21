"""Adapter: ARsens app project JSON  <->  domain model.

Mirrors JsonProjectStore.kt key-for-key, including the new ``origin`` field and the same
derive-on-absent rule for legacy projects (sensor: placement present => on_the_fly, else prepared;
marker: prepared). Keeping these in lock-step is what makes the app and this tool interchangeable.
"""
from __future__ import annotations

import json
from typing import Any

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


def _origin_from_wire(value, default: PlacementOrigin) -> PlacementOrigin:
    for o in PlacementOrigin:
        if o.value == value:
            return o
    return default


def _status_from_wire(value) -> SensorStatus:
    for s in SensorStatus:
        if s.value == value:
            return s
    return SensorStatus.PENDING


# --- sensors -----------------------------------------------------------------

def sensor_to_dict(s: Sensor) -> dict:
    d: dict[str, Any] = {
        "order": s.order,
        "id": s.id,
        "name": s.name,
        "side": s.side,
        "position_mm": s.position_mm.as_list(),
        "normal": s.normal.as_list(),
        "tolerance_mm": s.tolerance_mm,
        "instruction": s.instruction,
        "status": s.status.value,
        "origin": s.origin.value,
    }
    if s.reference_tag_id is not None:
        d["reference_tag_id"] = s.reference_tag_id
    if s.sensor_tag_id is not None:
        d["sensor_tag_id"] = s.sensor_tag_id
    if s.placement is not None:
        d["placement"] = s.placement
    if s.drift_correction is not None:
        d["drift_correction"] = s.drift_correction
    return d


def sensor_from_dict(d: dict) -> Sensor:
    has_placement = isinstance(d.get("placement"), dict)
    origin_wire = d.get("origin")
    if origin_wire:
        origin = _origin_from_wire(origin_wire, PlacementOrigin.PREPARED)
    else:
        origin = PlacementOrigin.ON_THE_FLY if has_placement else PlacementOrigin.PREPARED
    return Sensor(
        order=int(d.get("order", 0)),
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        side=str(d.get("side", "veld")),
        position_mm=MmPosition.from_list(d["position_mm"]),
        normal=FloatVector.from_list(d["normal"]) if "normal" in d else FloatVector(0.0, 1.0, 0.0),
        tolerance_mm=int(d.get("tolerance_mm", 50)),
        instruction=str(d.get("instruction", "")),
        status=_status_from_wire(d.get("status")),
        origin=origin,
        reference_tag_id=d.get("reference_tag_id"),
        sensor_tag_id=d.get("sensor_tag_id"),
        placement=d.get("placement"),
        drift_correction=d.get("drift_correction"),
    )


# --- markers -----------------------------------------------------------------

def marker_to_dict(m: Marker) -> dict:
    return {
        "id": m.id,
        "type": m.type,
        "size_mm": m.size_mm,
        "position_mm": m.position_mm.as_list(),
        "rotation_deg": m.rotation_deg.as_list(),
        "active": m.active,
        "pose_weight": m.pose_weight,
        "origin": m.origin.value,
    }


def marker_from_dict(d: dict) -> Marker:
    origin_wire = d.get("origin")
    origin = _origin_from_wire(origin_wire, PlacementOrigin.PREPARED) if origin_wire else PlacementOrigin.PREPARED
    return Marker(
        id=int(d["id"]),
        type=str(d.get("type", "apriltag")),
        size_mm=int(d.get("size_mm", 100)),
        position_mm=MmPosition.from_list(d["position_mm"]),
        rotation_deg=FloatVector.from_list(d["rotation_deg"]) if "rotation_deg" in d else FloatVector(0.0, 0.0, 0.0),
        active=bool(d.get("active", True)),
        pose_weight=float(d.get("pose_weight", 1.0)),
        origin=origin,
    )


# --- stl models --------------------------------------------------------------

def stl_model_to_dict(m: StlModel) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "file_name": m.file_name,
        "scale_percent": m.scale_percent,
        "offset_mm": m.offset_mm.as_list(),
        "rotation_deg": m.rotation_deg.as_list(),
        "visible": m.visible,
        "role": m.role,
    }


def stl_model_from_dict(d: dict) -> StlModel:
    return StlModel(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        file_name=str(d.get("file_name", "")),
        scale_percent=int(d.get("scale_percent", 100)),
        offset_mm=MmPosition.from_list(d["offset_mm"]) if "offset_mm" in d else MmPosition(0, 0, 0),
        rotation_deg=MmPosition.from_list(d["rotation_deg"]) if "rotation_deg" in d else MmPosition(0, 0, 0),
        visible=bool(d.get("visible", True)),
        role=str(d.get("role", "OTHER")),
    )


# --- project -----------------------------------------------------------------

def project_to_dict(p: Project) -> dict:
    d: dict[str, Any] = {
        "project_name": p.project_name,
        "model_file": p.model_file,
        "dimensions_mm": p.dimensions_mm.as_list(),
        "dimensions_locked": p.dimensions_locked,
        "sensors": [sensor_to_dict(s) for s in p.sensors],
        "markers": [marker_to_dict(m) for m in p.markers],
        "stl_models": [stl_model_to_dict(m) for m in p.stl_models],
    }
    if p.coordinate_frame is not None:
        d["coordinate_frame"] = p.coordinate_frame
    return d


def project_from_dict(d: dict) -> Project:
    return Project(
        project_name=str(d.get("project_name", "Transformer A")),
        model_file=str(d.get("model_file", "transformer_model.glb")),
        dimensions_mm=MmPosition.from_list(d["dimensions_mm"]) if "dimensions_mm" in d else MmPosition(10000, 5000, 3200),
        dimensions_locked=bool(d.get("dimensions_locked", False)),
        coordinate_frame=d.get("coordinate_frame"),
        sensors=sorted((sensor_from_dict(s) for s in d.get("sensors", [])), key=lambda s: s.order),
        markers=[marker_from_dict(m) for m in d.get("markers", [])],
        stl_models=[stl_model_from_dict(m) for m in d.get("stl_models", [])],
    )


def project_to_json(p: Project, indent: int = 2) -> str:
    return json.dumps(project_to_dict(p), indent=indent, ensure_ascii=False)


def project_from_json(text: str) -> Project:
    return project_from_dict(json.loads(text))


def load_project(path) -> Project:
    with open(path, "r", encoding="utf-8") as f:
        return project_from_json(f.read())


def save_project(p: Project, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(project_to_json(p))
