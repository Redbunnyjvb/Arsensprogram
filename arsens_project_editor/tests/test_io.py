import json

from app import json_io
from app.models import Marker, PlacementOrigin, Project, Sensor, SensorStatus


def _sample() -> Project:
    return Project(
        project_name="T",
        dimensions_mm=[10000, 5000, 3200],
        sensors=[
            Sensor(order=1, id="S1", name="a", position_mm=[2000, 0, 1000], tolerance_mm=50,
                   status=SensorStatus.OK, origin=PlacementOrigin.ON_THE_FLY, reference_tag_id=1),
            Sensor(order=2, id="S2", name="b", position_mm=[100, 100, 100], tolerance_mm=40),
        ],
        markers=[Marker(id=1, position_mm=[2000, 0, 1000], size_mm=100, rotation_deg=[0, 0, 0])],
    )


def test_json_roundtrip_preserves_fields():
    back = json_io.project_from_json(json_io.project_to_json(_sample()))
    assert back.project_name == "T"
    assert back.dimensions_mm == [10000, 5000, 3200]
    assert back.sensors[0].origin == PlacementOrigin.ON_THE_FLY
    assert back.sensors[0].status == SensorStatus.OK
    assert back.sensors[0].reference_tag_id == 1
    assert back.sensors[1].origin == PlacementOrigin.PREPARED
    assert back.markers[0].id == 1


def test_to_dict_uses_app_wire_values():
    d = json_io.project_to_dict(_sample())
    assert d["sensors"][0]["status"] == "ok"
    assert d["sensors"][0]["origin"] == "on_the_fly"
    assert d["markers"][0]["type"] == "apriltag"
    assert d["sensors"][0]["reference_tag_id"] == 1
    assert "reference_tag_id" not in d["sensors"][1]  # omitted when None, like the app


def test_legacy_origin_is_derived():
    legacy = {
        "project_name": "T", "dimensions_mm": [1000, 1000, 1000],
        "sensors": [
            {"order": 1, "id": "S1", "name": "", "side": "veld", "position_mm": [1, 2, 3],
             "tolerance_mm": 50, "status": "ok", "placement": {}},
            {"order": 2, "id": "S2", "name": "", "side": "veld", "position_mm": [4, 5, 6],
             "tolerance_mm": 50, "status": "pending"},
        ],
        "markers": [{"id": 1, "type": "apriltag", "size_mm": 100, "position_mm": [0, 0, 0],
                     "rotation_deg": [0, 0, 0]}],
    }
    back = json_io.project_from_json(json.dumps(legacy))
    assert back.sensors[0].origin == PlacementOrigin.ON_THE_FLY
    assert back.sensors[1].origin == PlacementOrigin.PREPARED
    assert back.markers[0].origin == PlacementOrigin.PREPARED


def test_opaque_placement_preserved():
    p = _sample()
    p.sensors[0].placement = {"grade": "high", "reprojection_error_mm": 1.5}
    back = json_io.project_from_json(json_io.project_to_json(p))
    assert back.sensors[0].placement == {"grade": "high", "reprojection_error_mm": 1.5}
