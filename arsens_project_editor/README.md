# ARsens Project Editor

Desktop app (PySide6 + PyVista) to prepare an ARsens project on a PC: load a 3D model, set the
transformer box, place sensors and AprilTags, align the model, validate, and export an
ARsens-compatible package.

Canonical frame: origin front-left-bottom · X+ right · Y+ back/depth · Z+ up · millimetres.

## Setup

```
py -3 -m venv .venv
.venv\Scripts\python -m pip install -e arsens_project_editor   # or: pip install PySide6 pyvista trimesh numpy pandas openpyxl pydantic
```

## Run

```
.venv\Scripts\python arsens_project_editor\main.py
```

## Test

```
.venv\Scripts\python -m pytest arsens_project_editor
```

## Layout

| Layer | File | Responsibility |
|-------|------|----------------|
| Geometry | `app/geometry.py` | tag center/rotation per plane, model transform `s·(c+R·(p−c))+offset`, operator↔box frame — pure, testable |
| Schema | `app/models.py` | pydantic models |
| IO | `app/json_io.py`, `app/excel_io.py` | project JSON (ARsens-compatible) + Excel |
| Mesh | `app/mesh_loader.py` | STL/OBJ/PLY via trimesh |
| Rules | `app/validation.py` | validation |
| Export | `app/export_package.py` | `arsens_project_export.zip` |
| View | `app/viewport.py`, `app/ui_mainwindow.py` | PyVista 3D scene + PySide6 window |

JSON is the source of truth; Excel is human-friendly input. Wire values match the ARsens app
(`status: pending/ok/fail`, `markers`, `origin`) so exported packages import straight into ARsens.
