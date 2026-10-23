"""docs/API_CONTRACT.md mentions every route the backend serves."""
import re

from config import BASE_DIR

CONTRACT = BASE_DIR.parent / "docs" / "API_CONTRACT.md"


def _normalise(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def test_every_route_is_in_the_api_contract():
    import main

    text = _normalise(CONTRACT.read_text(encoding="utf-8"))
    routes = [p for p in main.app.openapi()["paths"] if p not in ("/openapi.json", "/docs", "/redoc")]
    missing = [p for p in routes if _normalise(p) not in text]
    assert not missing, missing
