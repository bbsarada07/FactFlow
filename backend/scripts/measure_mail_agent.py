"""Measure the mail agent, rules-only, on the 14 demo emails (demo inbox provider): time per task
end to end, the analysis stages inside it, and the agent's own overhead (state machine, policy,
execution, audit). No model calls, no network. Run from backend/:

    venv\\Scripts\\python scripts/measure_mail_agent.py --db <throwaway.db>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from config import settings  # noqa: E402


async def main(db: Path) -> int:
    import secrets

    from database import connection
    from database.models import Email, MailTask
    from services import mail_agent
    from shield.providers.base import RawMessageRef
    from shield.schemas import UnifiedVerdict

    settings.ASYNC_DATABASE_URL = f"sqlite+aiosqlite:///{db.as_posix()}"
    settings.APPROVAL_SECRET = secrets.token_urlsafe(32)  # in-process only, so approval creation is measured
    settings.MAIL_AGENT_MAX_PER_MINUTE = 1000
    await connection.init_db()
    eml = mail_agent.eml_provider()
    rows = []
    for ref in await eml.list_new(None):
        t0 = time.perf_counter()
        task_id = await mail_agent.process(eml, RawMessageRef("eml", ref.message_id), use_llm=False)
        total = (time.perf_counter() - t0) * 1000
        async with connection.session_factory()() as s:
            task = await s.get(MailTask, task_id)
            v = UnifiedVerdict.model_validate((await s.get(Email, task.email_id)).verdict)
        analysis = v.latency_ms.total
        rows.append({"name": ref.message_id, "label": v.overall.label, "state": task.state,
                     "task_ms": round(total, 1), "analysis_ms": analysis, "agent_overhead_ms": round(total - analysis, 1),
                     "per_stage": v.latency_ms.per_stage, "llm_calls": 0 if v.llm_usage is None else v.llm_usage.llm_calls,
                     "steps": len(task.steps or []), "transitions": len(task.transitions or [])})
        print(f"{ref.message_id:38s} {v.overall.label:10s} {task.state:18s} task {total:6.1f} ms  analysis {analysis} ms")
        sample = {"14_mixed_false_claim_and_injection": "task_done.json", "13_quishing_qr": "task_awaiting_approval.json"}
        if ref.message_id in sample:
            view = await mail_agent.task_view(task_id)
            (BACKEND / "data" / "sample_verdicts" / sample[ref.message_id]).write_text(
                json.dumps(view, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    await connection.close_db()

    def pct(values, q):
        values = sorted(values)
        return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]

    stages = {}
    for r in rows:
        for k, val in r["per_stage"].items():
            stages.setdefault(k, []).append(val)
    summary = {
        "task_ms": {"p50": pct([r["task_ms"] for r in rows], 0.5), "p95": pct([r["task_ms"] for r in rows], 0.95)},
        "agent_overhead_ms": {"p50": pct([r["agent_overhead_ms"] for r in rows], 0.5),
                              "p95": pct([r["agent_overhead_ms"] for r in rows], 0.95)},
        "stage_median_ms": {k: round(statistics.median(v), 1) for k, v in stages.items()},
        "llm_calls_total": sum(r["llm_calls"] for r in rows),
    }
    out = {"date": date.today().isoformat(), "mode": "rules", "database": "SQLite (throwaway)", "rows": rows,
           "summary": summary}
    dest = BACKEND / "data" / "measurements" / f"mail_agent_{out['date']}.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    sys.exit(asyncio.run(main(ap.parse_args().db)))
