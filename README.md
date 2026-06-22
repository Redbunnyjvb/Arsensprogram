# ARsens Project Editor

Desktop app (PySide6 + PyVista) to prepare an ARsens project on a PC: load a 3D model, set the
transformer box, place sensors and AprilTags, align the model, validate, and export an
ARsens-compatible package.

## Run
Double-click **`START_3D_EDITOR.bat`** (uses the bundled `.venv`).

## Source & tests
The app lives in [`arsens_project_editor/`](arsens_project_editor/) — see its README for the layout.

```
.venv\Scripts\python -m pytest arsens_project_editor
```

The earlier Tkinter 2D prototype was removed; this 3D editor replaces it.
