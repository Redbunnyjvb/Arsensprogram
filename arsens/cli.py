"""Orchestration: wires the adapters together. No domain or format logic lives here.

    python -m arsens                 # launch the GUI (same as no command)
    python -m arsens new out.json --name "Trafo 1" --dims 10000 5000 3200
    python -m arsens json-to-excel in.json out.xlsx
    python -m arsens excel-to-json in.xlsx out.json
    python -m arsens build-package project.json out.arsenspkg --model tank.stl
    python -m arsens validate project.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import project_json as pj


def _cmd_new(args) -> None:
    from .model import MmPosition, Project
    project = Project(project_name=args.name, dimensions_mm=MmPosition(*args.dims))
    pj.save_project(project, args.out)
    print(f"Nieuw project -> {args.out}")


def _cmd_json_to_excel(args) -> None:
    from . import project_excel as px
    px.write_workbook(pj.load_project(args.inp), args.out)
    print(f"{args.inp} -> {args.out}")


def _cmd_excel_to_json(args) -> None:
    from . import project_excel as px
    pj.save_project(px.read_workbook(args.inp), args.out)
    print(f"{args.inp} -> {args.out}")


def _cmd_build_package(args) -> None:
    from . import package as pkg
    from .model import StlModel
    project = pj.load_project(args.project)
    sources = {Path(m).name: m for m in (args.model or [])}
    # Register any passed --model that the project doesn't reference yet, so a fresh project
    # plus a model bundles without a manual stl_models entry.
    existing = {m.file_name for m in project.stl_models}
    for file_name in sources:
        if file_name not in existing:
            project.stl_models.append(StlModel(id=file_name, name=Path(file_name).stem, file_name=file_name))
    out = pkg.build_package(project, args.out, sources)
    print(f"Pakket -> {out}")


def _cmd_validate(args) -> None:
    from . import validation as val
    inp = Path(args.inp)
    if inp.suffix.lower() == ".xlsx":
        from . import project_excel as px
        project = px.read_workbook(inp)
    else:
        project = pj.load_project(inp)
    issues = val.validate_project(project)
    if not issues:
        print("OK - geen problemen gevonden.")
        return
    for issue in issues:
        print(" -", issue)
    sys.exit(1)


def _cmd_gui(args) -> None:
    from .ui_app import main as gui_main
    gui_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arsens", description="ARsens project authoring tool")
    sub = parser.add_subparsers(dest="cmd")

    p_new = sub.add_parser("new", help="maak een leeg project")
    p_new.add_argument("out")
    p_new.add_argument("--name", default="Transformer A")
    p_new.add_argument("--dims", nargs=3, type=int, default=[10000, 5000, 3200], metavar=("X", "Y", "Z"))
    p_new.set_defaults(func=_cmd_new)

    p_j2x = sub.add_parser("json-to-excel", help="project JSON -> Excel")
    p_j2x.add_argument("inp")
    p_j2x.add_argument("out")
    p_j2x.set_defaults(func=_cmd_json_to_excel)

    p_x2j = sub.add_parser("excel-to-json", help="Excel -> project JSON")
    p_x2j.add_argument("inp")
    p_x2j.add_argument("out")
    p_x2j.set_defaults(func=_cmd_excel_to_json)

    p_pkg = sub.add_parser("build-package", help="bouw een .arsenspkg")
    p_pkg.add_argument("project")
    p_pkg.add_argument("out")
    p_pkg.add_argument("--model", action="append", help="pad naar een modelbestand (herhaalbaar)")
    p_pkg.set_defaults(func=_cmd_build_package)

    p_val = sub.add_parser("validate", help="controleer een project (JSON of Excel)")
    p_val.add_argument("inp")
    p_val.set_defaults(func=_cmd_validate)

    p_gui = sub.add_parser("gui", help="start de grafische interface")
    p_gui.set_defaults(func=_cmd_gui)

    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        # No subcommand -> launch the GUI.
        from .ui_app import main as gui_main
        gui_main()
        return
    func(args)
