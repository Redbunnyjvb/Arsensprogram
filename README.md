# ARsens projectvoorbereiding (Python-tool)

Maak en bewerk een ARsens-project buiten de telefoon — afmetingen, **sensoren en tags in XYZ**,
een 3D-model — en exporteer **één `.arsenspkg`** dat de app in één keer importeert. Wisselt naadloos
uit met de app: hetzelfde project-JSON in beide richtingen.

## Starten

- **GUI**: dubbelklik `start.bat` (of `python main.py`).
- **Deps voor Excel/mesh**: `pip install -r requirements.txt` (de GUI/JSON/pakket werken al zonder).

## Wat het kan

- Project opbouwen: naam, afmetingen (mm), sensoren, tags — met een bovenaanzicht-plattegrond.
- **Herkomst** per sensor/tag: `voorbereid` (oranje, nog te plaatsen) of `on_the_fly` (live). De
  app toont dit als kleur (oranje→blauw bij plaatsen) en als rapportkolom.
- 3D-model koppelen (STL/OBJ/PLY) en meebundelen.
- Im-/exporteren: JSON (verliesvrij), Excel (handmatig invullen), en het `.arsenspkg`-pakket.

## CLI

```
python -m arsens new project.json --name "Trafo 1" --dims 10000 5000 3200
python -m arsens json-to-excel project.json plan.xlsx
python -m arsens excel-to-json plan.xlsx project.json
python -m arsens build-package project.json plan.arsenspkg --model tank.stl
python -m arsens validate project.json
```

## Pakketformaat (`.arsenspkg`)

Een zip die de app in één actie importeert:

```
manifest.json   format_version, created_by, created_at, models[] (file_name + sha256 + bytes)
project.json    het app-project-JSON (incl. het origin/Herkomst-veld)
models/<naam>   het/de gekoppelde 3D-model(len)
```

## Architectuur (separation of concerns)

| Laag | Bestand | Verantwoordelijkheid |
|------|---------|----------------------|
| Domein | `arsens/model.py` | pure dataclasses, geen I/O |
| Adapter | `arsens/project_json.py` | app-JSON ⇄ model (spiegelt `JsonProjectStore.kt`) |
| Adapter | `arsens/project_excel.py` | Excel ⇄ model (openpyxl) |
| Adapter | `arsens/mesh.py` | STL/OBJ lezen, binaire STL schrijven |
| Adapter | `arsens/package.py` | `.arsenspkg` bouwen/lezen |
| Regels | `arsens/validation.py` | binnen-box, unieke id's, toleranties |
| Orkestratie | `arsens/cli.py`, `arsens/ui_app.py` | knopen de adapters aan elkaar |

Tests: `python -m pytest` (vanuit deze map).
