"""Makes ``app`` importable when running pytest from anywhere in this project."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
