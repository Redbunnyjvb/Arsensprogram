"""Adapter: read/write 3D meshes — pure stdlib so the tool runs without numpy.

Reads binary+ASCII STL and OBJ into a flat triangle list, and writes a clean BINARY STL (smaller and
faster for the app to parse than ASCII). Weld/decimate, PLY and preview rendering are the numpy-stl
path (v2); packaging copies any STL/OBJ/PLY through as-is, so the app still imports the original when
no conversion is requested.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

Vec3 = tuple[float, float, float]
Tri = tuple[Vec3, Vec3, Vec3]


@dataclass
class Mesh:
    triangles: list[Tri] = field(default_factory=list)

    def bounds(self) -> tuple[Vec3, Vec3]:
        if not self.triangles:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        verts = [v for t in self.triangles for v in t]
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        zs = [v[2] for v in verts]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def recentered(self) -> "Mesh":
        (mnx, mny, mnz), (mxx, mxy, mxz) = self.bounds()
        cx, cy, cz = (mnx + mxx) / 2, (mny + mxy) / 2, (mnz + mxz) / 2
        return Mesh([tuple((v[0] - cx, v[1] - cy, v[2] - cz) for v in t) for t in self.triangles])


def read_mesh(path, sample_to: int | None = None) -> Mesh:
    """Read a mesh into a flat triangle list.

    With ``sample_to`` set, return at most ~that many triangles, read efficiently (a binary STL is
    strided so a preview of a 400k-triangle model only materialises ~sample_to triangles — fast and
    low-memory). ``sample_to=None`` reads the full mesh (for packaging/conversion).
    """
    ext = Path(path).suffix.lower()
    if ext == ".stl":
        return _read_stl(Path(path), sample_to)
    if ext == ".obj":
        return _read_obj(Path(path), sample_to)
    raise ValueError(
        f"mesh.read_mesh ondersteunt .stl/.obj in pure modus (kreeg '{ext}'); "
        f".ply gaat as-is mee in het pakket of vereist numpy-stl."
    )


def _stride_for(count: int, sample_to: int | None) -> int:
    if sample_to and count > sample_to:
        return count // sample_to + 1
    return 1


def _read_stl(p: Path, sample_to: int | None = None) -> Mesh:
    data = p.read_bytes()
    # Robust binary detection: a binary STL is exactly 84 + 50*count bytes. This is reliable even
    # when a binary header happens to start with "solid" (the classic ASCII/binary trap).
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if 84 + count * 50 == len(data):
            return _read_binary_stl(data, count, sample_to)
    return _read_ascii_stl(data.decode("ascii", "replace"), sample_to)


def _read_binary_stl(data: bytes, count: int | None = None, sample_to: int | None = None) -> Mesh:
    if len(data) < 84:
        return Mesh()
    if count is None:
        count = struct.unpack_from("<I", data, 80)[0]
    stride = _stride_for(count, sample_to)
    tris: list[Tri] = []
    for i in range(0, count, stride):
        off = 84 + i * 50
        if off + 50 > len(data):
            break
        vals = struct.unpack_from("<12fH", data, off)
        v = vals[3:12]
        tris.append(((v[0], v[1], v[2]), (v[3], v[4], v[5]), (v[6], v[7], v[8])))
    return Mesh(tris)


def _read_ascii_stl(text: str, sample_to: int | None = None) -> Mesh:
    verts: list[Vec3] = []
    tris: list[Tri] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0].lower() == "vertex":
            verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
            if len(verts) == 3:
                tris.append((verts[0], verts[1], verts[2]))
                verts = []
    if sample_to and len(tris) > sample_to:
        tris = tris[::_stride_for(len(tris), sample_to)]
    return Mesh(tris)


def _read_obj(p: Path, sample_to: int | None = None) -> Mesh:
    vs: list[Vec3] = []
    faces: list[list[int]] = []
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("v "):
                _, x, y, z, *_ = line.split()
                vs.append((float(x), float(y), float(z)))
            elif line.startswith("f "):
                idx = []
                for tok in line.split()[1:]:
                    n = int(tok.split("/")[0])
                    idx.append(n - 1 if n > 0 else len(vs) + n)
                faces.append(idx)
    stride = _stride_for(len(faces), sample_to)
    tris: list[Tri] = []
    for fi in range(0, len(faces), stride):
        idx = faces[fi]
        for k in range(1, len(idx) - 1):
            tris.append((vs[idx[0]], vs[idx[k]], vs[idx[k + 1]]))
    return Mesh(tris)


def _normal(t: Tri) -> Vec3:
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    mag = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    return (nx / mag, ny / mag, nz / mag)


def write_binary_stl(mesh: Mesh, path) -> None:
    with open(path, "wb") as f:
        f.write(b"ARsens binary STL".ljust(80, b"\0"))
        f.write(struct.pack("<I", len(mesh.triangles)))
        for t in mesh.triangles:
            nx, ny, nz = _normal(t)
            f.write(struct.pack("<3f", nx, ny, nz))
            for v in t:
                f.write(struct.pack("<3f", float(v[0]), float(v[1]), float(v[2])))
            f.write(struct.pack("<H", 0))


def convert_to_binary_stl(src, dst, recenter: bool = False) -> Mesh:
    """Read any supported mesh and write a clean binary STL. Returns the (possibly recentered) mesh."""
    mesh = read_mesh(src)
    if recenter:
        mesh = mesh.recentered()
    write_binary_stl(mesh, dst)
    return mesh
