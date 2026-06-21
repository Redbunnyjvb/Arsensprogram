"""Entry point. No arguments -> launch the GUI; otherwise behaves as the CLI.

    python main.py                       # GUI
    python main.py build-package p.json out.arsenspkg --model tank.stl
"""
from arsens.cli import main

if __name__ == "__main__":
    main()
