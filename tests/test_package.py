from arsens import package as pkg
from arsens.model import MmPosition, PlacementOrigin, Project, Sensor, StlModel


def test_package_build_and_read_roundtrip(tmp_path):
    model = tmp_path / "tank.stl"
    model.write_bytes(b"BINARY-STL-BYTES-1234")
    project = Project(
        project_name="T",
        sensors=[Sensor(order=1, id="1", name="a", position_mm=MmPosition(1, 2, 3),
                        tolerance_mm=50, origin=PlacementOrigin.PREPARED)],
        stl_models=[StlModel(id="tank.stl", name="tank", file_name="tank.stl")],
    )
    out = tmp_path / "plan.arsenspkg"
    pkg.build_package(project, out, {"tank.stl": str(model)})

    back, manifest, models = pkg.read_package(out)
    assert back.project_name == "T"
    assert back.sensors[0].origin == PlacementOrigin.PREPARED
    assert models["tank.stl"] == b"BINARY-STL-BYTES-1234"
    assert manifest["format_version"] == 1
    assert manifest["models"][0]["file_name"] == "tank.stl"
    assert manifest["models"][0]["bytes"] == len(b"BINARY-STL-BYTES-1234")


def test_package_extracts_models_to_dir(tmp_path):
    model = tmp_path / "core.obj"
    model.write_bytes(b"obj-data")
    project = Project(project_name="T", stl_models=[StlModel(id="core.obj", name="core", file_name="core.obj")])
    out = tmp_path / "p.arsenspkg"
    pkg.build_package(project, out, {"core.obj": str(model)})

    extract = tmp_path / "extracted"
    _project, _manifest, models = pkg.read_package(out, extract_models_to=extract)
    assert (extract / "core.obj").read_bytes() == b"obj-data"
    assert models["core.obj"] == extract / "core.obj"
