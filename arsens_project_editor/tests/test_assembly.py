"""Tests for the wall-box assembly alignment, role detection, and click-place plane snapping
(ports of the ARsens app's estimateCoreBounds / buildTankFrame / detectFromName)."""
import numpy as np
import trimesh

from app import mesh_loader
from app.geometry import (
    PartGeom,
    TagPlane,
    core_bounds_from_faces,
    detect_role_from_name,
    nearest_plane,
    rotated_bounds_of_box,
    solve_assembly_alignment,
)

DIMS = (10000, 5000, 3200)


# --- role detection ----------------------------------------------------------

def test_detect_role_from_real_filenames():
    assert detect_role_from_name("1512_Tank") == "TANK"
    assert detect_role_from_name("1512_Cover") == "COVER"
    assert detect_role_from_name("1512_Core") == "CORE"
    assert detect_role_from_name("1512_Active Part") == "ACTIVE_PART"
    assert detect_role_from_name("1512_Wiksets") == "WIKSETS"
    assert detect_role_from_name("1512_Turrets_Bushing_CTs_AluPlate") == "BUSHINGS_TURRETS"
    assert detect_role_from_name("mystery_widget") == "OTHER"


def test_detect_role_cover_wins_over_tank():
    # "Tank cover" must read as the cover, not the tank.
    assert detect_role_from_name("Tank cover") == "COVER"
    assert detect_role_from_name("Tankdeksel") == "COVER"


# --- nearest plane (click-place snapping) ------------------------------------

def test_nearest_plane_each_face():
    dx, dy, dz = DIMS
    assert nearest_plane([dx / 2, 5, dz / 2], DIMS) == TagPlane.FRONT
    assert nearest_plane([dx / 2, dy - 5, dz / 2], DIMS) == TagPlane.BACK
    assert nearest_plane([5, dy / 2, dz / 2], DIMS) == TagPlane.LEFT
    assert nearest_plane([dx - 5, dy / 2, dz / 2], DIMS) == TagPlane.RIGHT
    assert nearest_plane([dx / 2, dy / 2, dz - 5], DIMS) == TagPlane.TOP


# --- rotated bounds ----------------------------------------------------------

def test_rotated_bounds_identity_for_zero_rotation():
    b = [0, 0, 0, 100, 200, 300]
    assert np.allclose(rotated_bounds_of_box(b, (0, 0, 0)), b)


def test_rotated_bounds_z90_swaps_xy_extents():
    rb = rotated_bounds_of_box([0, 0, 0, 100, 200, 300], (0, 0, 90))
    extents = np.asarray(rb[3:]) - np.asarray(rb[:3])
    assert np.allclose(extents, [200, 100, 300], atol=1e-6)


# --- wall box (excludes ribs) ------------------------------------------------

def test_core_bounds_excludes_a_thin_rib():
    # A solid 100x100x20 slab with a thin 4x4x80 rib standing on top (z up to 100).
    slab = trimesh.creation.box(extents=(100, 100, 20))
    slab.apply_translation([50, 50, 10])          # x,y in [0,100], z in [0,20]
    rib = trimesh.creation.box(extents=(4, 4, 80))
    rib.apply_translation([50, 50, 60])           # z in [20,100]
    mesh = trimesh.util.concatenate([slab, rib])

    full = np.asarray(mesh.bounds).reshape(6)
    assert full[5] >= 99.0                          # full bbox reaches the rib top (z=100)

    core = mesh_loader.core_bounds(mesh)
    assert core[2] < 2.0                            # wall z-min ~ 0 (slab bottom)
    assert core[5] < 30.0                           # wall z-max ~ 20 (slab top); rib dropped
    assert core[0] < 2.0 and core[3] > 98.0         # x wall spans the full slab
    assert core[1] < 2.0 and core[4] > 98.0         # y wall spans the full slab


# --- full assembly solve -----------------------------------------------------

def _box(xmin, ymin, zmin, xmax, ymax, zmax):
    return (xmin, ymin, zmin, xmax, ymax, zmax)


def test_solve_tank_cover_core_shared_frame():
    # Shared CAD frame: all parts centred on x=500,y=250. Cover modelled sitting on the tank rim
    # (z 300..360) with ribbing that overhangs in x/y/z — the wall box must ignore that overhang.
    tank = PartGeom(id="tank", role="TANK", name="Tank", full_bounds=_box(0, 0, 0, 1000, 500, 300),
                    core_bounds=_box(0, 0, 0, 1000, 500, 300))
    cover = PartGeom(id="cover", role="COVER", name="Cover",
                     full_bounds=_box(-20, -20, 300, 1020, 520, 420),   # conservator/ribs overhang
                     core_bounds=_box(0, 0, 300, 1000, 500, 360))       # 60 mm wall
    core = PartGeom(id="core", role="CORE", name="Core", full_bounds=_box(400, 200, 50, 600, 300, 250),
                    core_bounds=_box(400, 200, 50, 600, 300, 250))

    pl = solve_assembly_alignment([tank, cover, core], adopt_dims=True, current_dims=DIMS)
    assert pl is not None
    assert pl.tank_id == "tank"
    # Box = tank wall box in x/y; height = tank wall (300) + cover wall (60) = 360 — NOT inflated
    # by the cover's ribbing (which would give x>1000 and z up to 420).
    assert pl.dims == [1000, 500, 360]
    assert pl.offsets["tank"] == [0, 0, 0]
    assert pl.offsets["cover"] == [0, 0, 0]          # flange already on the rim in the shared frame
    assert pl.offsets["core"] == [0, 0, -50]         # interior dropped to the floor (z 50 -> 0)
    assert not pl.manual_ids


def test_solve_cover_lands_on_rim_when_not_shared():
    # Cover modelled at the origin (not in the tank's frame) -> its flange bottom (wall z-min) must
    # be lifted onto the tank rim (tank wall height = 300).
    tank = PartGeom(id="tank", role="TANK", name="Tank", full_bounds=_box(0, 0, 0, 1000, 500, 300),
                    core_bounds=_box(0, 0, 0, 1000, 500, 300))
    cover = PartGeom(id="cover", role="COVER", name="Cover",
                     full_bounds=_box(2000, 2000, 0, 3000, 2500, 60),
                     core_bounds=_box(2000, 2000, 0, 3000, 2500, 60))
    pl = solve_assembly_alignment([tank, cover], adopt_dims=True, current_dims=DIMS)
    assert pl is not None
    # Not a shared frame -> centred on the box in x/y and rim-aligned in z.
    assert pl.offsets["cover"][2] == 300             # wall z-min (0) -> tank rim (300)
    assert pl.dims[2] == 360                          # 300 tank + 60 cover wall


def test_solve_empty_returns_none():
    assert solve_assembly_alignment([], current_dims=DIMS) is None
