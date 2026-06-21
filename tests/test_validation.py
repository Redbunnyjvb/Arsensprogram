from arsens import validation as val
from arsens.model import Marker, MmPosition, Project, Sensor


def test_flags_dup_id_out_of_box_and_tolerance():
    p = Project(
        project_name="T",
        dimensions_mm=MmPosition(1000, 1000, 1000),
        sensors=[
            Sensor(order=1, id="a", name="", position_mm=MmPosition(100, 100, 100), tolerance_mm=50),
            Sensor(order=2, id="a", name="", position_mm=MmPosition(2000, 0, 0), tolerance_mm=0),
        ],
        markers=[Marker(id=1, position_mm=MmPosition(5000, 0, 0))],
    )
    text = " ".join(val.validate_project(p))
    assert "Dubbele sensor-id" in text
    assert "buiten de box" in text
    assert "tolerantie" in text


def test_clean_project_has_no_issues():
    p = Project(
        project_name="T",
        dimensions_mm=MmPosition(1000, 1000, 1000),
        sensors=[Sensor(order=1, id="a", name="", position_mm=MmPosition(100, 100, 100), tolerance_mm=50)],
        markers=[Marker(id=1, position_mm=MmPosition(10, 10, 10))],
    )
    assert val.validate_project(p) == []
