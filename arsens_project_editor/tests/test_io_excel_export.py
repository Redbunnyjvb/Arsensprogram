import numpy as np
import trimesh

from app import excel_io, export_package, mesh_loader
from app.models import Marker, PlacementOrigin, Project, Sensor, SensorStatus, StlModel


def test_excel_roundtrip(tmp_path):
    p = Project(
        project_name="T",
        dimensions_mm=[8000, 4000, 3000],
        sensors=[Sensor(order=1, id="S1", name="A", position_mm=[10, 20, 30], normal=[0, 1, 0],
                        tolerance_mm=40, status=SensorStatus.OK, origin=PlacementOrigin.ON_THE_FLY,
                        reference_tag_id=5, sensor_tag_id=200)],
        markers=[Marker(id=5, position_mm=[0, 0, 100], size_mm=80, rotation_deg=[0, 0, 90],
                        origin=PlacementOrigin.PREPARED)],
        stl_models=[StlModel(id="m1", name="body", file_name="body.stl", scale_percent=120,
                             offset_mm=[1, 2, 3], role="body")],
    )
    f = tmp_path / "p.xlsx"
    excel_io.write_workbook(p, f)
    back = excel_io.read_workbook(f)
    assert back.project_name == "T"
    assert back.dimensions_mm == [8000, 4000, 3000]
    s = back.sensors[0]
    assert (s.id, s.position_mm, s.tolerance_mm, s.reference_tag_id, s.sensor_tag_id) == ("S1", [10, 20, 30], 40, 5, 200)
    assert s.status == SensorStatus.OK and s.origin == PlacementOrigin.ON_THE_FLY
    t = back.markers[0]
    assert t.id == 5 and t.size_mm == 80 and t.rotation_deg == [0.0, 0.0, 90.0]
    m = back.stl_models[0]
    assert m.file_name == "body.stl" and m.scale_percent == 120 and m.offset_mm == [1, 2, 3]


def test_mesh_loader_box(tmp_path):
    box = trimesh.creation.box(extents=[100, 200, 300])
    f = tmp_path / "box.stl"
    box.export(str(f))
    m = mesh_loader.load_mesh(f)
    assert np.allclose(mesh_loader.extents(m), [100, 200, 300], atol=1e-3)
    assert np.allclose(mesh_loader.center(m), [0, 0, 0], atol=1e-6)
    assert mesh_loader.to_pyvista(m).n_points > 0


def test_mesh_raycast():
    box = trimesh.creation.box(extents=[100, 100, 100])  # centered, spans -50..50
    hit = mesh_loader.raycast(box, [0, 0, 200], [0, 0, -1])
    assert hit is not None and np.allclose(hit, [0, 0, 50], atol=1e-6)


def test_export_package_roundtrip(tmp_path):
    model = tmp_path / "body.stl"
    model.write_bytes(b"STL-BYTES-XYZ")
    p = Project(
        project_name="T",
        sensors=[Sensor(order=1, id="S1", name="a", position_mm=[1, 2, 3], tolerance_mm=50)],
        stl_models=[StlModel(id="m1", name="body", file_name="body.stl")],
    )
    out = tmp_path / "arsens_project_export.zip"
    export_package.build_export(p, out, {"body.stl": str(model)})
    project, manifest, names = export_package.read_export(out)
    assert project.project_name == "T"
    assert "project.json" in names
    assert "project_template.xlsx" in names
    assert "manifest.json" in names
    assert "models/body.stl" in names
    assert manifest["format_version"] == 1
    assert manifest["models"][0]["file_name"] == "body.stl"
