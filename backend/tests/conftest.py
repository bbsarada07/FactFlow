"""Make the backend package importable from tests (run `pytest` inside backend/)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
