import json

from arsens import project_json as pj
from arsens.model import (
    Marker,
    MmPosition,
    PlacementOrigin,
    Project,
    Sensor,
    SensorStatus,
)


def _sample() -> Project:
    return Project(
        project_name="T",
        sensors=[
            Sensor(order=1, id="1", name="a", position_mm=MmPosition(100, 100, 100),
                   tolerance_mm=50, status=SensorStatus.OK, origin=PlacementOrigin.ON_THE_FLY),
            Sensor(order=2, id="2", name="b", position_mm=MmPosition(200, 200, 200),
                   tolerance_mm=50, origin=PlacementOrigin.PREPARED),
        ],
        markers=[
            Marker(id=1, position_mm=MmPosition(0, 0, 0), origin=PlacementOrigin.PREPARED),
            Marker(id=2, position_mm=MmPosition(10, 10, 10), origin=PlacementOrigin.ON_THE_FLY),
        ],
    )


def test_model_json_roundtrip_preserves_origin_and_geometry():
    back = pj.project_from_json(pj.project_to_json(_sample()))
    assert back.sensors[0].origin == PlacementOrigin.ON_THE_FLY
    assert back.sensors[1].origin == PlacementOrigin.PREPARED
    assert {m.id: m.origin for m in back.markers} == {
        1: PlacementOrigin.PREPARED,
        2: PlacementOrigin.ON_THE_FLY,
    }
    assert back.sensors[0].position_mm == MmPosition(100, 100, 100)
    assert back.sensors[0].status == SensorStatus.OK


def test_absent_origin_derived_like_the_app():
    """Same contract as the Kotlin JsonProjectStoreTest: legacy projects without 'origin'."""
    legacy = {
        "project_name": "T",
        "sensors": [
            {"order": 1, "id": "1", "name": "a", "side": "veld", "position_mm": [1, 2, 3],
             "tolerance_mm": 50, "instruction": "", "status": "ok", "placement": {}},
            {"order": 2, "id": "2", "name": "b", "side": "veld", "position_mm": [4, 5, 6],
             "tolerance_mm": 50, "instruction": "", "status": "pending"},
        ],
        "markers": [
            {"id": 1, "type": "apriltag", "size_mm": 100, "position_mm": [0, 0, 0],
             "rotation_deg": [0, 0, 0]},
        ],
    }
    back = pj.project_from_json(json.dumps(legacy))
    assert back.sensors[0].origin == PlacementOrigin.ON_THE_FLY   # had a placement audit
    assert back.sensors[1].origin == PlacementOrigin.PREPARED     # no placement
    assert back.markers[0].origin == PlacementOrigin.PREPARED


def test_opaque_placement_blob_is_preserved():
    p = _sample()
    p.sensors[0].placement = {"grade": "high", "reprojection_error_mm": 1.5}
    back = pj.project_from_json(pj.project_to_json(p))
    assert back.sensors[0].placement == {"grade": "high", "reprojection_error_mm": 1.5}
