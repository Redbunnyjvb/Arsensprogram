"""Pure helpers behind the select/move drag and the in-view measure tool."""
import numpy as np

from app.geometry import (
    TagPlane,
    dominant_axis,
    inplane_deltas,
    is_light_color,
    nearest_index,
    project_point_to_plane,
    ray_plane_intersection,
)


def test_ray_plane_intersection_hits_axis_plane():
    # Ray from (5, -10, 7) along +Y hits the y=0 plane at (5, 0, 7).
    hit = ray_plane_intersection([5.0, -10.0, 7.0], [5.0, 10.0, 7.0],
                                 [0.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    assert hit is not None
    assert np.allclose(hit, [5.0, 0.0, 7.0])


def test_ray_plane_intersection_parallel_returns_none():
    # Ray travels in X only; the y=0 plane (normal +Y) is parallel → no hit.
    assert ray_plane_intersection([0.0, 5.0, 0.0], [10.0, 5.0, 0.0],
                                  [0.0, 0.0, 0.0], [0.0, 1.0, 0.0]) is None


def test_dominant_axis():
    assert dominant_axis([0.0, -1.0, 0.0]) == 1   # looking along Y (front/back view)
    assert dominant_axis([0.9, 0.1, 0.2]) == 0    # along X (left/right view)
    assert dominant_axis([0.1, 0.2, -0.97]) == 2  # along Z (top view)


def test_inplane_deltas_drops_axis_and_diagonal():
    # Y differs by a lot but is the dropped (depth) axis; the in-plane legs are a 3-4-5 triangle.
    d_a, d_b, diag, (a, b) = inplane_deltas([100.0, 50.0, 200.0], [400.0, 999.0, 600.0], drop_axis=1)
    assert (a, b) == (0, 2)
    assert d_a == 300.0   # ΔX
    assert d_b == 400.0   # ΔZ
    assert abs(diag - 500.0) < 1e-9


def test_nearest_index_snaps_within_threshold():
    pts = [[0, 0, 0], [100, 0, 0], [0, 200, 0]]
    assert nearest_index([90, 5, 0], pts, max_dist=30) == 1
    assert nearest_index([90, 5, 0], pts, max_dist=5) is None
    assert nearest_index([0, 0, 0], [], max_dist=10) is None


def test_project_point_to_plane_pins_fixed_axis():
    dims = (1000, 2000, 3000)
    assert list(project_point_to_plane([100, 500, 700], TagPlane.FRONT, dims)) == [100, 0, 700]
    assert list(project_point_to_plane([100, 500, 700], TagPlane.BACK, dims)) == [100, 2000, 700]
    assert list(project_point_to_plane([100, 500, 700], TagPlane.LEFT, dims)) == [0, 500, 700]
    assert list(project_point_to_plane([100, 500, 700], TagPlane.RIGHT, dims)) == [1000, 500, 700]
    assert list(project_point_to_plane([100, 500, 700], TagPlane.TOP, dims)) == [100, 500, 3000]


def test_is_light_color():
    assert is_light_color("#FFFFFF") is True
    assert is_light_color("#EEEEEE") is True
    assert is_light_color("#000000") is False
    assert is_light_color("#0E1726") is False   # the old dark background
    assert is_light_color("bogus") is True      # safe fallback
