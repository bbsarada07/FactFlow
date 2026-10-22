"""Measure the inbox pipeline on the 14 demo emails: latency per stage and total, rules-only and
with the LLM, tokens per email, and registry reuse for repeated claims. Writes:

  data/measurements/inbox_<date>.json      every run, as measured
  data/sample_verdicts/{safe,suspicious,dangerous}.json   real verdicts from the full pipeline

Run from backend/ (uses the models and search providers configured in .env, and a throwaway SQLite
database so no real data is touched):

    venv\\Scripts\\python scripts/measure_inbox.py --db <path-to-throwaway.db> [--skip-llm]

With --skip-llm only the rules-only pass runs, and the sample verdicts are rules-only verdicts
(their "mode" field says so).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import secrets
import statistics
import sys
import time
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from config import settings  # noqa: E402

DEMO = sorted((BACKEND / "data" / "demo_emails").glob("*.eml"))
SAMPLES = {"safe": "02_benign_meeting_invite", "suspicious": "13_quishing_qr", "dangerous": "14_mixed_false_claim_and_injection"}


def pct(values: list[int], q: float) -> int:
    if not values:
        return 0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


async def run_one(name: str, raw: bytes, use_llm: bool, source: str = "demo") -> dict:
    from agents.inbox_pipeline import InboxOptions, analyze
    from database import connection
    from database.models import Email
    from shield.email_parser import parse_input
    from shield.scan import PIPELINE_VERSION

    pe = parse_input(raw, source)
    async with connection.session_factory()() as s:
        row = Email(source=source, sha256=pe.sha256, pipeline_version=PIPELINE_VERSION,
                    mode="full" if use_llm else "rules", status="processing", subject=pe.subject)
        s.add(row)
        await s.commit()
        email_id = row.id
    t0 = time.perf_counter()
    v = await analyze(email_id, raw, InboxOptions(source=source, use_llm=use_llm))
    wall = int((time.perf_counter() - t0) * 1000)
    if v is None:
        return {"name": name, "failed": True, "wall_ms": wall}
    usage = v.llm_usage.model_dump() if v.llm_usage else None
    return {
        "name": name, "label": v.overall.label, "score": v.overall.score, "input_type": v.input_type,
        "total_ms": v.latency_ms.total, "wall_ms": wall, "per_stage": v.latency_ms.per_stage, "usage": usage,
        "claims": [{"claim": c.claim, "verdict": c.verdict} for c in v.components.claims.items],
        "analysis_failures": v.analysis_failures, "language": v.explanation.user_language,
        "verdict": v.model_dump(mode="json"),
    }


async def main(db: Path, rules_repeats: int, skip_llm: bool) -> int:
    from database import connection

    settings.ASYNC_DATABASE_URL = f"sqlite+aiosqlite:///{db.as_posix()}"
    settings.APPROVAL_SECRET = secrets.token_urlsafe(32)  # in-process only, so the approval step is measured
    await connection.init_db()
    out = {"date": date.today().isoformat(), "machine": f"{platform.system()} {platform.release()}, "
           f"{platform.processor() or platform.machine()}, Python {platform.python_version()}",
           "models": {"nano": settings.NANO_MODEL, "ultra": settings.ULTRA_MODEL}, "database": "SQLite (throwaway)",
           "rules": [], "full": [], "repeat": []}

    print("rules-only:")
    rules_verdicts = {}
    for path in DEMO:
        runs = [await run_one(path.stem, path.read_bytes(), use_llm=False) for _ in range(rules_repeats)]
        med = sorted(runs, key=lambda r: r["total_ms"])[len(runs) // 2]
        rules_verdicts[path.stem] = med["verdict"]
        med = {k: v for k, v in med.items() if k != "verdict"}
        med["runs_ms"] = [r["total_ms"] for r in runs]
        out["rules"].append(med)
        print(f"  {path.stem:38s} {med['label']:10s} {med['total_ms']:5d} ms")

    print("full (LLM): skipped" if skip_llm else "full (LLM):")
    for path in [] if skip_llm else DEMO:
        r = await run_one(path.stem, path.read_bytes(), use_llm=True)
        out["full"].append(r)
        tokens = (r.get("usage") or {}).get("total_tokens")
        print(f"  {path.stem:38s} {r.get('label', 'FAILED'):10s} {r.get('total_ms', r['wall_ms']):6d} ms  {tokens} tokens")

    print("repeat (claims answered from the registry):")
    for r in [x for x in out["full"] if x.get("claims")]:
        path = next(p for p in DEMO if p.stem == r["name"])
        raw = path.read_bytes().replace(b"Message-ID: <demo-", b"Message-ID: <repeat-demo-")
        again = await run_one(r["name"], raw, use_llm=True)
        out["repeat"].append({k: v for k, v in again.items() if k != "verdict"})
        print(f"  {r['name']:38s} {again['usage']['total_tokens']} tokens, "
              f"{again['usage']['claims_from_registry']} claim(s) from the registry")

    samples = BACKEND / "data" / "sample_verdicts"
    samples.mkdir(parents=True, exist_ok=True)
    for kind, name in SAMPLES.items():
        full = next((x for x in out["full"] if x["name"] == name and not x.get("failed")), None)
        verdict = full["verdict"] if full else rules_verdicts[name]
        (samples / f"{kind}.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in out["full"]:
        r.pop("verdict", None)

    full_ok = [r for r in out["full"] if not r.get("failed")]
    out["summary"] = {
        "rules_total_ms": {"p50": pct([r["total_ms"] for r in out["rules"]], 0.5),
                           "p95": pct([r["total_ms"] for r in out["rules"]], 0.95)},
        "full_total_ms": {"p50": pct([r["total_ms"] for r in full_ok], 0.5), "p95": pct([r["total_ms"] for r in full_ok], 0.95)},
        "full_tokens": {"p50": pct([r["usage"]["total_tokens"] for r in full_ok], 0.5),
                        "max": max((r["usage"]["total_tokens"] for r in full_ok), default=0),
                        "sum": sum(r["usage"]["total_tokens"] for r in full_ok)},
        "failed_runs": [r["name"] for r in out["full"] if r.get("failed")],
        "mean_rules_ms": round(statistics.mean(r["total_ms"] for r in out["rules"]), 1),
    }
    dest = BACKEND / "data" / "measurements" / f"inbox_{out['date']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out["summary"], indent=2))
    print(f"wrote {dest}")
    await connection.close_db()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True, help="throwaway SQLite file (created if missing)")
    ap.add_argument("--rules-repeats", type=int, default=5)
    ap.add_argument("--skip-llm", action="store_true", help="rules-only pass only (no model calls)")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.db, args.rules_repeats, args.skip_llm)))
