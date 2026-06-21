import pytest

pytest.importorskip("openpyxl")

from arsens import project_excel as px  # noqa: E402
from arsens.model import (  # noqa: E402
    FloatVector,
    Marker,
    MmPosition,
    PlacementOrigin,
    Project,
    Sensor,
    SensorStatus,
)


def test_excel_roundtrip_preserves_authoring_fields(tmp_path):
    p = Project(
        project_name="T",
        dimensions_mm=MmPosition(8000, 4000, 3000),
        sensors=[Sensor(order=1, id="s1", name="A", position_mm=MmPosition(10, 20, 30),
                        tolerance_mm=40, sensor_tag_id=200,
                        origin=PlacementOrigin.ON_THE_FLY, status=SensorStatus.OK)],
        markers=[Marker(id=5, position_mm=MmPosition(1, 2, 3), size_mm=80,
                        rotation_deg=FloatVector(0.0, 0.0, 90.0), origin=PlacementOrigin.PREPARED)],
    )
    xlsx = tmp_path / "plan.xlsx"
    px.write_workbook(p, xlsx)
    back = px.read_workbook(xlsx)

    assert back.project_name == "T"
    assert back.dimensions_mm == MmPosition(8000, 4000, 3000)
    s = back.sensors[0]
    assert (s.id, s.position_mm, s.tolerance_mm, s.sensor_tag_id) == ("s1", MmPosition(10, 20, 30), 40, 200)
    assert s.origin == PlacementOrigin.ON_THE_FLY
    assert s.status == SensorStatus.OK
    m = back.markers[0]
    assert m.id == 5 and m.size_mm == 80
    assert m.rotation_deg == FloatVector(0.0, 0.0, 90.0)
    assert m.origin == PlacementOrigin.PREPARED
