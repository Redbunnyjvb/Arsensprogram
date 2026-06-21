"""Pure geometry for the ARsens canonical transformer frame.

No UI and no I/O — fully unit-testable. Canonical frame:
  origin = front-left-bottom; X+ = right, Y+ = back/depth, Z+ = up; millimetres.
  dimensions = [x_length, y_depth, z_height].

Tag planes:    Front Y=0 · Back Y=dy · Left X=0 · Right X=dx · Top Z=dz
Plane U/V:     Front/Back U=+X V=+Z · Left/Right U=+Y V=+Z · Top U=+X V=+Y
Tag rotation:  Front [0,0,0] · Back [0,0,180] · Left [0,0,-90] · Right [0,0,90] · Top [-90,0,0]
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

import numpy as np

Vec3 = np.ndarray


class TagPlane(str, Enum):
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"


class MeasureAnchor(str, Enum):
    CENTER = "center"
    BOTTOM_LEFT_EDGE = "bottom_left_edge"


class OriginCorner(str, Enum):
    FRONT_LEFT_BOTTOM = "front_left_bottom"
    FRONT_RIGHT_BOTTOM = "front_right_bottom"
    BACK_LEFT_BOTTOM = "back_left_bottom"
    BACK_RIGHT_BOTTOM = "back_right_bottom"


_TAG_ROTATION = {
    TagPlane.FRONT: (0.0, 0.0, 0.0),
    TagPlane.BACK: (0.0, 0.0, 180.0),
    TagPlane.LEFT: (0.0, 0.0, -90.0),
    TagPlane.RIGHT: (0.0, 0.0, 90.0),
    TagPlane.TOP: (-90.0, 0.0, 0.0),
}

_X = np.array([1.0, 0.0, 0.0])
_Y = np.array([0.0, 1.0, 0.0])
_Z = np.array([0.0, 0.0, 1.0])


# --- tags --------------------------------------------------------------------

def tag_rotation_for(plane: TagPlane) -> tuple[float, float, float]:
    return _TAG_ROTATION[plane]


def plane_uv_axes(plane: TagPlane) -> tuple[Vec3, Vec3]:
    """Unit U and V axes of the plane's local 2D frame, in canonical box coordinates."""
    if plane in (TagPlane.FRONT, TagPlane.BACK):
        return _X, _Z
    if plane in (TagPlane.LEFT, TagPlane.RIGHT):
        return _Y, _Z
    return _X, _Y  # TOP


def plane_fixed_axis(plane: TagPlane, dims) -> tuple[int, float]:
    """The axis index pinned by the plane and its exact value (0 or a max dimension)."""
    dx, dy, dz = (float(d) for d in dims)
    return {
        TagPlane.FRONT: (1, 0.0),
        TagPlane.BACK: (1, dy),
        TagPlane.LEFT: (0, 0.0),
        TagPlane.RIGHT: (0, dx),
        TagPlane.TOP: (2, dz),
    }[plane]


def plane_uv_extent(plane: TagPlane, dims) -> tuple[float, float]:
    """Maximum U and V (mm) of the plane rectangle."""
    dx, dy, dz = (float(d) for d in dims)
    if plane in (TagPlane.FRONT, TagPlane.BACK):
        return dx, dz
    if plane in (TagPlane.LEFT, TagPlane.RIGHT):
        return dy, dz
    return dx, dy  # TOP


def tag_uv_of_point(plane: TagPlane, point) -> tuple[float, float]:
    """Project a 3D point onto the plane's (U, V) axes."""
    u_ax, v_ax = plane_uv_axes(plane)
    p = np.asarray(point, dtype=float)
    return float(p @ u_ax), float(p @ v_ax)


def tag_position_for(plane: TagPlane, u_mm: float, v_mm: float, dims, size_mm: float = 0.0) -> Vec3:
    """Tag CENTER position (mm) for plane-local (u, v). Clamps the center so a tag of [size_mm]
    stays fully inside the plane rectangle, and pins the fixed plane component exactly to 0/max."""
    u_ax, v_ax = plane_uv_axes(plane)
    fixed_idx, fixed_val = plane_fixed_axis(plane, dims)
    u_max, v_max = plane_uv_extent(plane, dims)
    half = size_mm / 2.0
    u = float(np.clip(u_mm, half, max(half, u_max - half)))
    v = float(np.clip(v_mm, half, max(half, v_max - half)))
    pos = u * u_ax + v * v_ax
    pos[fixed_idx] = fixed_val
    return pos


def tag_measured_point_to_center(plane: TagPlane, measured, anchor: MeasureAnchor,
                                 size_mm: float, dims) -> Vec3:
    """Convert a measured point on the plane to the tag CENTER.

    For BOTTOM_LEFT_EDGE the measured point is the tag's lower-left corner, so the center is half
    the tag size further along +U and +V. The result is clamped and pinned like tag_position_for.
    """
    u, v = tag_uv_of_point(plane, measured)
    if anchor == MeasureAnchor.BOTTOM_LEFT_EDGE:
        u += size_mm / 2.0
        v += size_mm / 2.0
    return tag_position_for(plane, u, v, dims, size_mm)


# --- model transform ---------------------------------------------------------

def euler_xyz_matrix(rx_deg: float, ry_deg: float, rz_deg: float) -> np.ndarray:
    """Rotation matrix applying X, then Y, then Z (degrees) → R = Rz @ Ry @ Rx."""
    rx, ry, rz = np.radians([rx_deg, ry_deg, rz_deg])
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    rot_x = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    rot_y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rot_z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rot_z @ rot_y @ rot_x


def transform_points(points, center, scale_percent: float, rotation_deg, offset_mm) -> np.ndarray:
    """Project model points into the box frame: ``s * (c + R * (p - c)) + offset_mm``.

    Uniform scale s = scale_percent / 100. ``points`` may be a single point or an (N, 3) array.
    """
    pts = np.asarray(points, dtype=float)
    c = np.asarray(center, dtype=float)
    rot = euler_xyz_matrix(*rotation_deg)
    s = scale_percent / 100.0
    off = np.asarray(offset_mm, dtype=float)
    rotated = (pts - c) @ rot.T  # apply R to each (row) vector
    return s * (c + rotated) + off


# --- coordinate frame (operator <-> canonical box) ---------------------------

def _corner_basis(origin_corner: OriginCorner, dims, flip_x: bool, flip_y: bool, flip_z: bool):
    dx, dy, dz = (float(d) for d in dims)
    base = {
        OriginCorner.FRONT_LEFT_BOTTOM: (0.0, 0.0, 0.0),
        OriginCorner.FRONT_RIGHT_BOTTOM: (dx, 0.0, 0.0),
        OriginCorner.BACK_LEFT_BOTTOM: (0.0, dy, 0.0),
        OriginCorner.BACK_RIGHT_BOTTOM: (dx, dy, 0.0),
    }[origin_corner]
    sx = -1.0 if base[0] == dx else 1.0
    sy = -1.0 if base[1] == dy else 1.0
    sz = 1.0
    if flip_x:
        sx = -sx
    if flip_y:
        sy = -sy
    if flip_z:
        sz = -sz
    return np.asarray(base), np.asarray([sx, sy, sz])


def operator_to_box(point_op, dims,
                    origin_corner: OriginCorner = OriginCorner.FRONT_LEFT_BOTTOM,
                    flip_x: bool = False, flip_y: bool = False, flip_z: bool = False) -> np.ndarray:
    base, sign = _corner_basis(origin_corner, dims, flip_x, flip_y, flip_z)
    return base + sign * np.asarray(point_op, dtype=float)


def box_to_operator(point_box, dims,
                    origin_corner: OriginCorner = OriginCorner.FRONT_LEFT_BOTTOM,
                    flip_x: bool = False, flip_y: bool = False, flip_z: bool = False) -> np.ndarray:
    base, sign = _corner_basis(origin_corner, dims, flip_x, flip_y, flip_z)
    return sign * (np.asarray(point_box, dtype=float) - base)


def point_inside_box(point, dims, eps: float = 1e-6) -> bool:
    p = np.asarray(point, dtype=float)
    d = np.asarray([float(x) for x in dims])
    return bool(np.all(p >= -eps) and np.all(p <= d + eps))


def plane_of_point(point, dims, tol: float = 1.0) -> Optional[TagPlane]:
    """Which tag plane a point lies on (within [tol] mm), or None. Front/Back/Left/Right/Top only
    (the bottom Z=0 is not a tag plane)."""
    x, y, z = (float(v) for v in point)
    dx, dy, dz = (float(d) for d in dims)
    if abs(y) <= tol:
        return TagPlane.FRONT
    if abs(y - dy) <= tol:
        return TagPlane.BACK
    if abs(x) <= tol:
        return TagPlane.LEFT
    if abs(x - dx) <= tol:
        return TagPlane.RIGHT
    if abs(z - dz) <= tol:
        return TagPlane.TOP
    return None


def plane_outward_normal(plane: TagPlane) -> Vec3:
    """Outward-facing normal of a tag plane (the direction the tag faces)."""
    return {
        TagPlane.FRONT: np.array([0.0, -1.0, 0.0]),
        TagPlane.BACK: np.array([0.0, 1.0, 0.0]),
        TagPlane.LEFT: np.array([-1.0, 0.0, 0.0]),
        TagPlane.RIGHT: np.array([1.0, 0.0, 0.0]),
        TagPlane.TOP: np.array([0.0, 0.0, 1.0]),
    }[plane]
