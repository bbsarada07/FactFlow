"""The example env files name every variable the code reads (as a setting line or in a comment)."""
import os
import re
from pathlib import Path

from config import BASE_DIR, Settings

FRONTEND = BASE_DIR.parent / "frontend"


def example_names(path: Path) -> set[str]:
    """Every UPPER_CASE name in the file: assigned (NAME=) or mentioned in a comment."""
    return set(re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", path.read_text(encoding="utf-8")))


def assigned_names(path: Path) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", path.read_text(encoding="utf-8"), re.MULTILINE))


def test_backend_env_example_names_every_setting():
    names = example_names(BASE_DIR / ".env.example")
    missing = [n for n in Settings.model_fields if n not in names]
    assert not missing, missing


def test_backend_env_example_assigns_only_real_settings():
    unused = assigned_names(BASE_DIR / ".env.example") - set(Settings.model_fields) - {"DATABASE_URL"}
    assert not unused, unused  # DATABASE_URL is kept for tools such as psql and says so in a comment


def test_frontend_env_example_names_every_env_read():
    used = set()
    for folder in ("pages", "components", "lib"):
        for root, _dirs, files in os.walk(FRONTEND / folder):
            for f in files:
                if f.endswith((".js", ".jsx", ".mjs", ".ts", ".tsx")):
                    used |= set(re.findall(r"process\.env\.([A-Z_]+)", Path(root, f).read_text(encoding="utf-8")))
    used.discard("NODE_ENV")
    missing = sorted(used - example_names(FRONTEND / ".env.local.example"))
    assert not missing, missing
