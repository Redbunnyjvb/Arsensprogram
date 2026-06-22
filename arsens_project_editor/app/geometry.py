"""Pure geometry for the ARsens canonical transformer frame.

No UI and no I/O — fully unit-testable. Canonical frame:
  origin = front-left-bottom; X+ = right, Y+ = back/depth, Z+ = up; millimetres.
  dimensions = [x_length, y_depth, z_height].

Tag planes:    Front Y=0 · Back Y=dy · Left X=0 · Right X=dx · Top Z=dz
Plane U/V:     Front/Back U=+X V=+Z · Left/Right U=+Y V=+Z · Top U=+X V=+Y
Tag rotation:  Front [0,0,0] · Back [0,0,180] · Left [0,0,-90] · Right [0,0,90] · Top [-90,0,0]
"""
from __future__ import annotations

from dataclasses import dataclass, field
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


def nearest_plane(point, dims) -> TagPlane:
    """The tag plane (Front/Back/Left/Right/Top) a point is closest to. Used by click-to-place:
    the user clicks a wall in 3D and the tag snaps to the nearest box face. Bottom (Z=0) is not a
    tag plane, mirroring ``plane_of_point``."""
    x, y, z = (float(v) for v in point)
    dx, dy, dz = (float(d) for d in dims)
    dists = {
        TagPlane.FRONT: abs(y),
        TagPlane.BACK: abs(y - dy),
        TagPlane.LEFT: abs(x),
        TagPlane.RIGHT: abs(x - dx),
        TagPlane.TOP: abs(z - dz),
    }
    return min(dists, key=dists.get)


# --- part role from filename (port of ARsens StlPartRole.detectFromName) ----

#: Wire role strings, matching the ARsens app (``StlPartRole.wireName``).
ROLE_TANK = "TANK"
ROLE_COVER = "COVER"
ROLE_CORE = "CORE"
ROLE_ACTIVE_PART = "ACTIVE_PART"
ROLE_WIKSETS = "WIKSETS"
ROLE_BUSHINGS_TURRETS = "BUSHINGS_TURRETS"
ROLE_OTHER = "OTHER"

WIRE_ROLES = {ROLE_TANK, ROLE_COVER, ROLE_CORE, ROLE_ACTIVE_PART, ROLE_WIKSETS,
              ROLE_BUSHINGS_TURRETS, ROLE_OTHER}


def detect_role_from_name(name: str) -> str:
    """Guess the assembly role from a file/part name (NX exports: "Tank.stl", "Active Part.stl"…).
    Order matters: a "Tank cover" must read as COVER, and "active" contains "ct" so it precedes the
    CT rule. Port of ``StlPartRole.detectFromName`` in the ARsens app."""
    lower = (name or "").lower()
    if any(k in lower for k in ("cover", "deksel", "lid", "kap")):
        return ROLE_COVER
    if "tank" in lower:
        return ROLE_TANK
    if "active" in lower or "actief" in lower:
        return ROLE_ACTIVE_PART
    if "core" in lower or "kern" in lower:
        return ROLE_CORE
    if any(k in lower for k in ("wikset", "winding", "wikkel", "coil")):
        return ROLE_WIKSETS
    if any(k in lower for k in ("bushing", "turret", "aluplate", "alu plate")):
        return ROLE_BUSHINGS_TURRETS
    if lower == "ct" or lower.startswith("ct ") or lower.startswith("ct_") \
            or " ct" in lower or "_ct" in lower:
        return ROLE_BUSHINGS_TURRETS
    return ROLE_OTHER


# --- wall box + assembly alignment (port of ARsens estimateCoreBounds / buildTankFrame) ---

def rotated_bounds_of_box(bounds6, rotation_deg) -> np.ndarray:
    """Axis-aligned bounds of a box [minx,miny,minz,maxx,maxy,maxz] after rotating its 8 corners
    about the box centre. Identity for the common zero-rotation case (the only case the NX exports
    hit); the rotated path keeps the extents correct for hand-rotated parts."""
    b = np.asarray(bounds6, dtype=float)
    if all(abs(float(r)) < 1e-9 for r in rotation_deg):
        return b.copy()
    center = (b[:3] + b[3:]) / 2.0
    rot = euler_xyz_matrix(*[float(r) for r in rotation_deg])
    corners = np.array([[b[i], b[j], b[k]] for i in (0, 3) for j in (1, 4) for k in (2, 5)])
    rc = (corners - center) @ rot.T + center
    return np.array([rc[:, 0].min(), rc[:, 1].min(), rc[:, 2].min(),
                     rc[:, 0].max(), rc[:, 1].max(), rc[:, 2].max()])


def core_bounds_from_faces(centroids, normals, areas, full_bounds, bins: int = 256) -> np.ndarray:
    """The "wall box": the dominant solid extent per axis, ignoring ribs/radiators/protrusions.

    Port of ``StlMesh.estimateCoreBounds``. For each axis, the area of faces whose normal is mostly
    along that axis (|n|>=0.8) is binned by face-centroid position; the wall spans the first/last
    bins holding at least 25% of the peak bin's area. Thin ribs contribute little area and fall
    below the threshold, so they drop out. Falls back to ``full_bounds`` per axis when undecidable.
    """
    fb = np.asarray(full_bounds, dtype=float).reshape(6).copy()
    result = fb.copy()
    centroids = np.asarray(centroids, dtype=float).reshape(-1, 3)
    normals = np.asarray(normals, dtype=float).reshape(-1, 3)
    areas = np.asarray(areas, dtype=float).reshape(-1)
    if centroids.shape[0] == 0:
        return result
    lo = fb[:3]
    rng = fb[3:] - fb[:3]
    absn = np.abs(normals)
    # A unit normal can have at most one component >= 0.8 (0.8^2 + 0.8^2 > 1), so the first
    # dominant axis is unique — mirrors the Kotlin "first a with |n[a]|>=0.8, break".
    mask = absn >= 0.8
    has = mask.any(axis=1)
    dom = np.argmax(mask, axis=1)
    for axis in range(3):
        if rng[axis] <= 1e-3:
            continue
        sel = has & (dom == axis)
        if not np.any(sel):
            continue
        hist = np.zeros(bins, dtype=float)
        bin_idx = np.clip(((centroids[sel, axis] - lo[axis]) / rng[axis] * bins).astype(int),
                          0, bins - 1)
        np.add.at(hist, bin_idx, areas[sel])
        peak = float(hist.max())
        if peak <= 0.0:
            continue
        above = np.nonzero(hist >= peak * 0.25)[0]
        if above.size == 0:
            continue
        low_bin, high_bin = int(above[0]), int(above[-1])
        if high_bin <= low_bin:
            continue
        bin_width = rng[axis] / bins
        result[axis] = lo[axis] + (low_bin + 0.5) * bin_width
        result[axis + 3] = lo[axis] + (high_bin + 0.5) * bin_width
    return result


@dataclass
class PartGeom:
    """Per-part input to :func:`solve_assembly_alignment` (model-space, pre-scale/offset)."""
    id: str
    role: str = ROLE_OTHER
    name: str = ""
    scale_percent: int = 100
    full_bounds: tuple = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    core_bounds: tuple = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    rotation_deg: tuple = (0, 0, 0)
    offset_mm: tuple = (0, 0, 0)  # current offset, kept for parts that can't be auto-placed


@dataclass
class AssemblyPlacement:
    dims: list  # [x, y, z] mm
    offsets: dict  # id -> [x, y, z] mm
    manual_ids: set = field(default_factory=set)  # parts left where they were (place by hand)
    tank_id: str = ""


def _ri(v) -> int:
    return int(round(float(v)))


def solve_assembly_alignment(parts, *, adopt_dims: bool = True, dims_locked: bool = False,
                             current_dims=None, floor_offset: int = 0) -> Optional[AssemblyPlacement]:
    """Place a multi-part assembly in the canonical box from the TANK reference, matching the ARsens
    app (``buildTankFrame`` + ``placeInTankFrame`` + ``sharesTankFrame``). Uses each part's WALL box
    (``core_bounds``) — not the full bbox — so ribbing/radiators don't inflate the box or lift the
    cover. Returns ``None`` if ``parts`` is empty.

    Placement: tank min-corner → origin and (optionally) box = tank wall box; box height extends to
    the cover-wall top when a cover is present; the cover's flange rests on the tank rim; interior
    parts (core/active/wiksets) sit on the floor (as a shared group when they share a CAD frame);
    bushings/other keep their position (only re-centred in X/Y on a shared frame, else "manual").
    """
    parts = list(parts)
    if not parts:
        return None
    current_dims = list(current_dims) if current_dims is not None else [1, 1, 1]

    def vol(p: PartGeom) -> float:
        b = p.full_bounds
        return max(b[3] - b[0], 0.0) * max(b[4] - b[1], 0.0) * max(b[5] - b[2], 0.0)

    def wall(p: PartGeom) -> np.ndarray:
        return rotated_bounds_of_box(p.core_bounds, p.rotation_deg)

    def full(p: PartGeom) -> np.ndarray:
        return rotated_bounds_of_box(p.full_bounds, p.rotation_deg)

    def is_zero_rot(p: PartGeom) -> bool:
        return all(abs(float(r)) < 1e-9 for r in p.rotation_deg)

    # Box-master: largest TANK, else a part named "tank", else largest COVER, else largest part.
    tanks = [p for p in parts if p.role == ROLE_TANK]
    named = next((p for p in parts if "tank" in (p.name or "").lower()), None)
    covers_all = [p for p in parts if p.role == ROLE_COVER]
    if tanks:
        tank = max(tanks, key=vol)
    elif named is not None:
        tank = named
    elif covers_all:
        tank = max(covers_all, key=vol)
    else:
        tank = max(parts, key=vol)

    tw = wall(tank)
    ts = tank.scale_percent / 100.0
    tank_top_z = (tw[5] - tw[2]) * ts  # real tank rim, independent of dims.z; the cover rests here

    cover = max((p for p in parts if p.role == ROLE_COVER and p.id != tank.id), key=vol, default=None)
    if cover is not None:
        cw = wall(cover)
        box_height = tank_top_z + (cw[5] - cw[2]) * (cover.scale_percent / 100.0)
    else:
        box_height = tank_top_z

    if adopt_dims and not dims_locked:
        dims = [max(1, _ri((tw[3] - tw[0]) * ts)),
                max(1, _ri((tw[4] - tw[1]) * ts)),
                max(1, _ri(box_height))]
    else:
        dims = [int(d) for d in current_dims]

    tank_offset = [_ri(-tw[0] * ts), _ri(-tw[1] * ts), _ri(-tw[2] * ts)]
    tank_mid_x = (tw[0] + tw[3]) / 2.0
    tank_mid_y = (tw[1] + tw[4]) / 2.0
    tank_w = max(tw[3] - tw[0], 1.0)
    tank_d = max(tw[4] - tw[1], 1.0)

    def shares(p: PartGeom) -> bool:
        # Shared CAD frame: all parts centred on the same X/Y as the tank wall → the tank offset is
        # exactly right for them and asymmetric protrusions stay put instead of being mis-centred.
        if not is_zero_rot(p) or not is_zero_rot(tank):
            return False
        if p.scale_percent != tank.scale_percent:
            return False
        w = wall(p)
        mx, my = (w[0] + w[3]) / 2.0, (w[1] + w[4]) / 2.0
        return abs(mx - tank_mid_x) <= tank_w * 0.12 and abs(my - tank_mid_y) <= tank_d * 0.12

    # Interior (core/active/wiksets) sharing one Z-frame → placed as a group so their relative
    # heights (windings float above the floor) are preserved.
    interior = [p for p in parts
                if p.id != tank.id and p.role in (ROLE_CORE, ROLE_ACTIVE_PART, ROLE_WIKSETS)]
    shared_interior = [p for p in interior if shares(p)]
    shared_z_group: set = set()
    group_min_z = 0.0
    if len(shared_interior) >= 2:
        z_ranges = [(full(p)[2], full(p)[5]) for p in shared_interior]
        z_mids = [(lo + hi) / 2.0 for lo, hi in z_ranges]
        max_h = max(hi - lo for lo, hi in z_ranges)
        if max(z_mids) - min(z_mids) <= max_h * 0.5:
            shared_z_group = {p.id for p in shared_interior}
            group_min_z = min(lo for lo, _ in z_ranges)

    offsets: dict = {}
    manual_ids: set = set()
    for p in parts:
        if p.id == tank.id:
            offsets[p.id] = list(tank_offset)
            continue
        s = p.scale_percent / 100.0
        f, w = full(p), wall(p)
        sh = shares(p)
        if p.role in (ROLE_BUSHINGS_TURRETS, ROLE_OTHER):
            if sh:
                offsets[p.id] = [tank_offset[0], tank_offset[1], int(p.offset_mm[2])]
            else:
                offsets[p.id] = [int(c) for c in p.offset_mm]  # keep where it is
                manual_ids.add(p.id)
            continue
        if sh:
            off_x, off_y = tank_offset[0], tank_offset[1]
        else:
            off_x = _ri(dims[0] / 2.0 - (w[0] + w[3]) / 2.0 * s)
            off_y = _ri(dims[1] / 2.0 - (w[1] + w[4]) / 2.0 * s)
        if p.role == ROLE_COVER:
            off_z = _ri(tank_top_z - w[2] * s)  # flange bottom on the tank rim
        elif p.id in shared_z_group:
            off_z = _ri(-group_min_z * s) + floor_offset
        else:
            off_z = _ri(-f[2] * s) + floor_offset
        offsets[p.id] = [off_x, off_y, off_z]

    return AssemblyPlacement(dims=dims, offsets=offsets, manual_ids=manual_ids, tank_id=tank.id)
