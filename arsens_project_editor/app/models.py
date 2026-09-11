"""Pydantic schema for an ARsens project.

Wire values deliberately match the ARsens app (so exported packages import straight in):
  status   -> pending | ok | fail
  origin   -> prepared | on_the_fly
  markers  -> AprilTag reference markers
Positions are integer millimetres in the canonical box frame.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class SensorStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    FAIL = "fail"


class PlacementOrigin(str, Enum):
    PREPARED = "prepared"
    ON_THE_FLY = "on_the_fly"


class OriginCorner(str, Enum):
    FRONT_LEFT_BOTTOM = "front_left_bottom"
    FRONT_RIGHT_BOTTOM = "front_right_bottom"
    BACK_LEFT_BOTTOM = "back_left_bottom"
    BACK_RIGHT_BOTTOM = "back_right_bottom"


def _round_int_triple(v):
    return [int(round(float(x))) for x in v]


class CoordinateFrame(BaseModel):
    model_config = ConfigDict(extra="ignore")
    origin_corner: OriginCorner = OriginCorner.FRONT_LEFT_BOTTOM
    flip_x: bool = False
    flip_y: bool = False
    flip_z: bool = False


class Sensor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    order: int
    id: str
    name: str = ""
    side: str = "veld"
    position_mm: list[int]
    normal: list[float] = [0.0, 1.0, 0.0]
    tolerance_mm: int = 50
    instruction: str = ""
    status: SensorStatus = SensorStatus.PENDING
    origin: PlacementOrigin = PlacementOrigin.PREPARED
    reference_tag_id: Optional[int] = None
    sensor_tag_id: Optional[int] = None
    # Opaque ARsens app fields, preserved verbatim on round-trip.
    placement: Optional[dict] = None
    drift_correction: Optional[dict] = None

    @field_validator("position_mm", mode="before")
    @classmethod
    def _round_pos(cls, v):
        return _round_int_triple(v)


class Marker(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    type: str = "apriltag"
    size_mm: int = 100
    position_mm: list[int]
    rotation_deg: list[float] = [0.0, 0.0, 0.0]
    active: bool = True
    pose_weight: float = 1.0
    origin: PlacementOrigin = PlacementOrigin.PREPARED

    @field_validator("position_mm", mode="before")
    @classmethod
    def _round_pos(cls, v):
        return _round_int_triple(v)


class StlModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str = ""
    file_name: str
    scale_percent: int = 100
    offset_mm: list[int] = [0, 0, 0]
    rotation_deg: list[int] = [0, 0, 0]
    visible: bool = True
    role: str = "OTHER"

    @field_validator("offset_mm", "rotation_deg", mode="before")
    @classmethod
    def _round_triple(cls, v):
        return _round_int_triple(v)


class Project(BaseModel):
    # Preserve newer/future ARsens project fields that this desktop editor does not
    # explicitly understand yet (e.g. scanned-wall calibration metadata).
    model_config = ConfigDict(extra="allow")
    project_name: str = "Transformer A"
    model_file: str = "transformer_model.glb"
    dimensions_mm: list[int] = [10000, 5000, 3200]
    dimensions_locked: bool = False
    coordinate_frame: CoordinateFrame = CoordinateFrame()
    sensors: list[Sensor] = []
    markers: list[Marker] = []
    stl_models: list[StlModel] = []

    @field_validator("dimensions_mm", mode="before")
    @classmethod
    def _round_dims(cls, v):
        return _round_int_triple(v)
