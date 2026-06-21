"""ARsens Project Editor — PySide6 desktop app to prepare ARsens projects.

Layers (separation of concerns):
  geometry.py        pure canonical-frame math (tags, transform, coordinate frame) — no I/O/UI
  models.py          pydantic schema for project/sensor/marker/model/coordinate frame
  json_io.py         project JSON <-> models (ARsens app-compatible wire format)
  excel_io.py        Excel workbook <-> models (human-friendly authoring)
  mesh_loader.py     STL/OBJ/PLY load + bounds/center/raycast (trimesh)
  validation.py      project validation rules
  export_package.py  arsens_project_export.zip builder
  viewport.py        PyVista 3D scene (box, models, tags, sensors)
  ui_mainwindow.py   PySide6 main window wiring it together
"""

__version__ = "0.1.0"
