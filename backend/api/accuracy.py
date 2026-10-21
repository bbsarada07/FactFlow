"""GET /api/accuracy — the last complete bench run, read from disk. Nothing here is hard-coded."""
import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["accuracy"])

# Written by scripts/run_bench.py only after a full run with no errors.
RESULTS_PATH = Path(__file__).resolve().parents[1] / "tests" / "bench" / "results" / "latest.json"
NO_RUN = {"complete": False, "message": "No complete run yet"}


@router.get("/accuracy")
async def accuracy():
    """Run date, model names, counts, the expected-vs-got rows and the rows that did not match.

    A missing or unreadable results file is reported as "No complete run yet".
    """
    try:
        run = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return NO_RUN
    if not isinstance(run, dict) or not isinstance(run.get("rows"), list):
        return NO_RUN
    rows = [
        {k: r.get(k) for k in ("id", "claim", "expected", "got", "sources", "strong", "gaps")}
        for r in run["rows"]
        if isinstance(r, dict)
    ]
    return {
        "complete": True,
        "run_at": run.get("run_at"),
        "models": run.get("models") or {},
        "counts": run.get("counts") or {},
        "rows": rows,
        "known_failures": [r for r in rows if r["got"] != r["expected"]],
    }
