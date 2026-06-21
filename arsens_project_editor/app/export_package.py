"""Build the ARsens export package (zip):

    arsens_project_export.zip
      project.json
      models/<model files>
      project_template.xlsx
      manifest.json
"""
from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

from . import excel_io, json_io
from .models import Project

PKG_FORMAT_VERSION = 1


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_export(project: Project, out_path, model_sources: dict | None = None,
                 issues=None, created_by: str = "arsens-project-editor") -> Path:
    """Write ``project`` + its model files into an export zip. ``model_sources`` maps a
    ``file_name`` (as referenced in project.stl_models) to a path on disk."""
    out_path = Path(out_path)
    sources = dict(model_sources or {})
    models_meta = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for model in project.stl_models:
            src = sources.get(model.file_name)
            if src is None:
                continue
            data = Path(src).read_bytes()
            z.writestr(f"models/{model.file_name}", data)
            models_meta.append({"file_name": model.file_name, "sha256": _sha256(data), "bytes": len(data)})

        z.writestr("project.json", json_io.project_to_json(project))

        buf = io.BytesIO()
        excel_io.write_workbook(project, buf, issues)
        z.writestr("project_template.xlsx", buf.getvalue())

        z.writestr("manifest.json", json.dumps({
            "format_version": PKG_FORMAT_VERSION,
            "created_by": created_by,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "models": models_meta,
        }, indent=2))
    return out_path


def read_export(path):
    """Returns (project, manifest, names) — for verifying a built package."""
    path = Path(path)
    with zipfile.ZipFile(path, "r") as z:
        names = z.namelist()
        project = json_io.project_from_json(z.read("project.json").decode("utf-8"))
        manifest = json.loads(z.read("manifest.json").decode("utf-8")) if "manifest.json" in names else {}
    return project, manifest, names
