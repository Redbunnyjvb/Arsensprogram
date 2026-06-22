"""Mesh loading + analysis via trimesh, and conversion to PyVista for the viewport."""
from __future__ import annotations

import numpy as np
import trimesh


def load_mesh(path) -> trimesh.Trimesh:
    """Load STL/OBJ/PLY (and anything trimesh supports) as a single Trimesh."""
    mesh = trimesh.load(str(path), force="mesh")
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
    return mesh


def bounds(mesh) -> np.ndarray:
    """(2, 3) array of [min_xyz, max_xyz]."""
    return np.asarray(mesh.bounds, dtype=float)


def extents(mesh) -> np.ndarray:
    """Bounding-box size [sx, sy, sz]."""
    return np.asarray(mesh.extents, dtype=float)


def center(mesh) -> np.ndarray:
    """Bounding-box center."""
    b = bounds(mesh)
    return (b[0] + b[1]) / 2.0


def to_pyvista(mesh):
    import pyvista as pv
    return pv.wrap(mesh)


def core_bounds(mesh) -> np.ndarray:
    """The "wall box" [minx,miny,minz,maxx,maxy,maxz] of a trimesh: the dominant solid extent,
    ignoring ribs/radiators/protrusions. Wraps :func:`geometry.core_bounds_from_faces` with the
    mesh's per-face centroids, normals and areas. Cache the 6 floats at import — it's far lighter
    than keeping the (possibly 100 MB) mesh around."""
    from . import geometry as geo
    return geo.core_bounds_from_faces(
        mesh.triangles_center, mesh.face_normals, mesh.area_faces, np.asarray(mesh.bounds).reshape(6))


def raycast(mesh, origin, direction):
    """First surface hit of a ray, or None."""
    locations, _, _ = mesh.ray.intersects_location([np.asarray(origin, float)],
                                                    [np.asarray(direction, float)])
    if len(locations) == 0:
        return None
    o = np.asarray(origin, float)
    return min(locations, key=lambda p: float(np.linalg.norm(p - o)))
