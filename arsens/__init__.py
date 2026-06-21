"""ARsens project authoring toolkit.

Separation of concerns:
  - model.py         pure domain dataclasses (no I/O, no format logic)
  - project_json.py  adapter: ARsens app project JSON  <->  model  (mirrors JsonProjectStore.kt)
  - project_excel.py adapter: .xlsx authoring sheets    <->  model
  - mesh.py          adapter: STL/OBJ/PLY read + normalize + write (model prep for the app)
  - package.py       adapter: .arsenspkg bundle (project.json + models/* + manifest)
  - validation.py    domain rules (inside-box, unique ids, tolerances)
  - cli.py           orchestration only (wires the adapters together)
"""

__version__ = "0.1.0"
