import numpy as np

from app.geometry import (
    MeasureAnchor,
    OriginCorner,
    TagPlane,
    box_to_operator,
    euler_xyz_matrix,
    operator_to_box,
    tag_measured_point_to_center,
    tag_position_for,
    tag_rotation_for,
    transform_points,
)

DIMS = (10000, 5000, 3200)


def test_tag_rotation_for():
    assert tag_rotation_for(TagPlane.FRONT) == (0, 0, 0)
    assert tag_rotation_for(TagPlane.BACK) == (0, 0, 180)
    assert tag_rotation_for(TagPlane.LEFT) == (0, 0, -90)
    assert tag_rotation_for(TagPlane.RIGHT) == (0, 0, 90)
    assert tag_rotation_for(TagPlane.TOP) == (-90, 0, 0)


def test_tag_position_for_each_plane_pins_fixed_axis():
    assert np.allclose(tag_position_for(TagPlane.FRONT, 2000, 1000, DIMS, 100), [2000, 0, 1000])
    assert np.allclose(tag_position_for(TagPlane.BACK, 2000, 1000, DIMS, 100), [2000, 5000, 1000])
    assert np.allclose(tag_position_for(TagPlane.LEFT, 2000, 1000, DIMS, 100), [0, 2000, 1000])
    assert np.allclose(tag_position_for(TagPlane.RIGHT, 2000, 1000, DIMS, 100), [10000, 2000, 1000])
    assert np.allclose(tag_position_for(TagPlane.TOP, 2000, 1000, DIMS, 100), [2000, 1000, 3200])


def test_tag_position_clamps_within_plane_rectangle():
    # u way past max, v negative -> clamped to [half, max-half]; half = 100 for size 200.
    p = tag_position_for(TagPlane.FRONT, 100000, -100, DIMS, 200)
    assert np.allclose(p, [9900, 0, 100])


def test_measured_point_to_center_bottom_left_edge_front():
    measured = [1000, 0, 500]  # lower-left corner on the Front plane
    c = tag_measured_point_to_center(TagPlane.FRONT, measured, MeasureAnchor.BOTTOM_LEFT_EDGE, 100, DIMS)
    assert np.allclose(c, [1050, 0, 550])
    c_center = tag_measured_point_to_center(TagPlane.FRONT, measured, MeasureAnchor.CENTER, 100, DIMS)
    assert np.allclose(c_center, [1000, 0, 500])


def test_measured_point_to_center_left_uses_y_z():
    measured = [0, 800, 400]  # Left plane: U=+Y, V=+Z
    c = tag_measured_point_to_center(TagPlane.LEFT, measured, MeasureAnchor.BOTTOM_LEFT_EDGE, 80, DIMS)
    assert np.allclose(c, [0, 840, 440])


def test_euler_xyz_identity_and_z180():
    assert np.allclose(euler_xyz_matrix(0, 0, 0), np.eye(3))
    r = euler_xyz_matrix(0, 0, 180)
    assert np.allclose(r @ [1, 0, 0], [-1, 0, 0], atol=1e-9)
    assert np.allclose(r @ [0, 1, 0], [0, -1, 0], atol=1e-9)


def test_transform_identity_scale_offset():
    pts = np.array([[0, 0, 0], [100, 0, 0], [0, 200, 0]], float)
    out = transform_points(pts, [50, 50, 0], 100, (0, 0, 0), [0, 0, 0])
    assert np.allclose(out, pts)
    out2 = transform_points(pts, [50, 50, 0], 200, (0, 0, 0), [1000, 0, 0])
    assert np.allclose(out2, 2 * pts + np.array([1000, 0, 0]))


def test_transform_rotation_about_center():
    # 180 deg about z about center (50,50,0): point (100,50) mirrors to (0,50).
    out = transform_points([100, 50, 0], [50, 50, 0], 100, (0, 0, 180), [0, 0, 0])
    assert np.allclose(out, [0, 50, 0], atol=1e-9)


def test_frame_default_is_identity():
    p = [1000, 2000, 300]
    assert np.allclose(operator_to_box(p, DIMS), p)
    assert np.allclose(box_to_operator(p, DIMS), p)


def test_frame_front_right_corner_flips_x():
    box = operator_to_box([1000, 0, 0], DIMS, OriginCorner.FRONT_RIGHT_BOTTOM)
    assert np.allclose(box, [9000, 0, 0])


def test_frame_roundtrip_all_corners_and_flips():
    p_op = np.array([1000, 2000, 300], float)
    for corner in OriginCorner:
        for fx in (False, True):
            for fy in (False, True):
                for fz in (False, True):
                    box = operator_to_box(p_op, DIMS, corner, fx, fy, fz)
                    back = box_to_operator(box, DIMS, corner, fx, fy, fz)
                    assert np.allclose(back, p_op)
