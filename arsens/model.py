"""Pure domain model mirroring the ARsens app's project structures.

No I/O and no format logic live here — adapters (project_json, project_excel) translate to/from
this. Opaque blobs (placement, drift_correction, coordinate_frame) are kept as raw dicts so a JSON
round-trip is lossless without modelling AR-audit internals in the tool.

The two independent axes that the overhaul is built on:
  - status: SensorStatus   -> the dot COLOUR  (pending = orange/todo, ok = blue/placed)
  - origin: PlacementOrigin -> the report LABEL (prepared = voorbereid, on_the_fly = live)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SensorStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    FAIL = "fail"


class PlacementOrigin(str, Enum):
    PREPARED = "prepared"
    ON_THE_FLY = "on_the_fly"


@dataclass
class MmPosition:
    """Integer millimetre triple (matches the app's MmPosition, also used for int rotations)."""

    x: int
    y: int
    z: int

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.z]

    @staticmethod
    def from_list(v) -> "MmPosition":
        return MmPosition(int(v[0]), int(v[1]), int(v[2]))


@dataclass
class FloatVector:
    x: float
    y: float
    z: float

    def as_list(self) -> list[float]:
        return [self.x, self.y, self.z]

    @staticmethod
    def from_list(v) -> "FloatVector":
        return FloatVector(float(v[0]), float(v[1]), float(v[2]))


@dataclass
class Sensor:
    order: int
    id: str
    name: str
    position_mm: MmPosition
    tolerance_mm: int
    side: str = "veld"
    instruction: str = ""
    normal: FloatVector = field(default_factory=lambda: FloatVector(0.0, 1.0, 0.0))
    status: SensorStatus = SensorStatus.PENDING
    origin: PlacementOrigin = PlacementOrigin.PREPARED
    reference_tag_id: Optional[int] = None
    sensor_tag_id: Optional[int] = None
    placement: Optional[dict] = None        # opaque AR-audit snapshot (preserved verbatim)
    drift_correction: Optional[dict] = None  # opaque blob


@dataclass
class Marker:
    """An AprilTag reference marker."""

    id: int
    position_mm: MmPosition
    size_mm: int = 100
    type: str = "apriltag"
    rotation_deg: FloatVector = field(default_factory=lambda: FloatVector(0.0, 0.0, 0.0))
    active: bool = True
    pose_weight: float = 1.0
    origin: PlacementOrigin = PlacementOrigin.PREPARED


@dataclass
class StlModel:
    id: str
    name: str
    file_name: str
    scale_percent: int = 100
    offset_mm: MmPosition = field(default_factory=lambda: MmPosition(0, 0, 0))
    # The app stores model rotation as an int-triple (reuses MmPosition), unlike marker rotation.
    rotation_deg: MmPosition = field(default_factory=lambda: MmPosition(0, 0, 0))
    visible: bool = True
    role: str = "OTHER"


@dataclass
class Project:
    project_name: str
    model_file: str = "transformer_model.glb"
    dimensions_mm: MmPosition = field(default_factory=lambda: MmPosition(10000, 5000, 3200))
    dimensions_locked: bool = False
    coordinate_frame: Optional[dict] = None  # opaque; app falls back to its default frame when None
    sensors: list[Sensor] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    stl_models: list[StlModel] = field(default_factory=list)
