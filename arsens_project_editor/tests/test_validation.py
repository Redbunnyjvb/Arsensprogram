from app import validation as val
from app.models import Marker, Project, Sensor

DIMS = [10000, 5000, 3200]


def test_clean_project_has_no_errors():
    p = Project(
        project_name="T",
        dimensions_mm=DIMS,
        sensors=[Sensor(order=1, id="S1", name="", position_mm=[2000, 1000, 500], tolerance_mm=50, reference_tag_id=1)],
        markers=[Marker(id=1, position_mm=[2000, 0, 1000], size_mm=100)],
    )
    issues = val.validate_project(p)
    assert not val.has_errors(issues), [str(i) for i in issues]


def test_catches_core_errors():
    p = Project(
        project_name="T",
        dimensions_mm=[0, 5000, 3200],
        sensors=[
            Sensor(order=1, id="S1", name="", position_mm=[100, 100, 100], tolerance_mm=0),
            Sensor(order=2, id="S1", name="", position_mm=[100, 100, 100], tolerance_mm=50, reference_tag_id=99),
        ],
        markers=[Marker(id=5, position_mm=[2000, 1000, 500], size_mm=100)],  # not on any plane
    )
    msgs = " ".join(str(i) for i in val.validate_project(p))
    assert "dimensions must be > 0" in msgs
    assert "Duplicate sensor id" in msgs
    assert "tolerance must be > 0" in msgs
    assert "does not lie exactly on a plane" in msgs
    assert "references tag 99 which does not exist" in msgs
