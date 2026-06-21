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


def raycast(mesh, origin, direction):
    """First surface hit of a ray, or None."""
    locations, _, _ = mesh.ray.intersects_location([np.asarray(origin, float)],
                                                    [np.asarray(direction, float)])
    if len(locations) == 0:
        return None
    o = np.asarray(origin, float)
    return min(locations, key=lambda p: float(np.linalg.norm(p - o)))
