from arsens import mesh


def test_binary_stl_roundtrip(tmp_path):
    t1 = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    t2 = ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    p = tmp_path / "m.stl"
    mesh.write_binary_stl(mesh.Mesh([t1, t2]), p)
    back = mesh.read_mesh(p)
    assert len(back.triangles) == 2
    assert back.triangles[0][1] == (1.0, 0.0, 0.0)


def test_obj_read_and_fan_triangulation(tmp_path):
    # A quad face -> two triangles via fan triangulation.
    p = tmp_path / "m.obj"
    p.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n")
    back = mesh.read_mesh(p)
    assert len(back.triangles) == 2
    assert back.triangles[0][0] == (0.0, 0.0, 0.0)


def test_bounds_and_recenter():
    m = mesh.Mesh([((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0))])
    (mn, mx) = m.bounds()
    assert mn == (0.0, 0.0, 0.0)
    assert mx == (2.0, 2.0, 0.0)
    (cmn, cmx) = m.recentered().bounds()
    assert cmn == (-1.0, -1.0, 0.0)
