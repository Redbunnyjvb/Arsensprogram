"""Adapter: the .arsenspkg bundle = a zip the app imports in one action.

Layout:
    manifest.json   format_version, created_by, created_at, models[] (file_name + sha256 + bytes)
    project.json    the app project JSON (origin fields included)
    models/<file_name>   the referenced STL/OBJ/PLY file(s)
"""
from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path

from . import project_json as pj
from .model import Project

PKG_FORMAT_VERSION = 1
MODELS_DIR = "models"


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build_package(project: Project, out_path, model_sources: dict | None = None,
                  created_by: str = "arsens-tool") -> Path:
    """Write ``project`` + its model files into an .arsenspkg zip.

    ``model_sources`` maps ``file_name`` (as referenced in project.stl_models) -> a path on disk.
    Model entries without a provided source are kept in the project but skipped in the archive.
    """
    out_path = Path(out_path)
    sources = dict(model_sources or {})
    models_meta = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for model in project.stl_models:
            src = sources.get(model.file_name)
            if src is None:
                continue
            data = Path(src).read_bytes()
            z.writestr(f"{MODELS_DIR}/{model.file_name}", data)
            models_meta.append({
                "file_name": model.file_name,
                "sha256": _sha256(data),
                "bytes": len(data),
            })
        manifest = {
            "format_version": PKG_FORMAT_VERSION,
            "created_by": created_by,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "models": models_meta,
        }
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("project.json", pj.project_to_json(project))
    return out_path


def read_package(pkg_path, extract_models_to=None):
    """Returns (project, manifest, models).

    ``models`` maps file_name -> raw bytes, or to the written Path when ``extract_models_to`` is given.
    """
    pkg_path = Path(pkg_path)
    with zipfile.ZipFile(pkg_path, "r") as z:
        names = z.namelist()
        project = pj.project_from_json(z.read("project.json").decode("utf-8"))
        manifest = json.loads(z.read("manifest.json").decode("utf-8")) if "manifest.json" in names else {}
        models: dict = {}
        prefix = f"{MODELS_DIR}/"
        for name in names:
            if name.startswith(prefix) and not name.endswith("/"):
                file_name = name[len(prefix):]
                data = z.read(name)
                if extract_models_to is not None:
                    dest = Path(extract_models_to) / file_name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    models[file_name] = dest
                else:
                    models[file_name] = data
    return project, manifest, models
