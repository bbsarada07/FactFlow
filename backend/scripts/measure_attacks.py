"""Attack success rate measurement script (Phase 4A).

Runs each attack email in shield=off about 20 times and records how often the attack
actually executed (an outbox entry that the hidden text asked for), and the same count
for shield=on.

Output goes to backend/data/local/attack_measurements_<timestamp>.json and a summary table.
If the LLM quota is unavailable, it does NOT use fake models; it marks the numbers "pending, not measured".
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]  # this file lives in backend/scripts/
sys.path.insert(0, str(BACKEND_DIR))

from config import settings
from database import connection
from models import groq_client
from services import llm_status
from shield import benchmark, sandbox_agent

LOCAL_DATA_DIR = BACKEND_DIR / "data" / "local"
DEMO_DIR = BACKEND_DIR / "data" / "demo_emails"


async def check_llm_reachability() -> bool:
    """Check if the real LLM endpoint is currently reachable and has quota."""
    if not settings.GROQ_API_KEY:
        return False
    if llm_status.breaker.remaining() > 0:
        return False
    try:
        res = await asyncio.wait_for(
            groq_client.call_nano(
                system="Reply with valid JSON {\"status\":\"ok\"}.",
                user="ping",
                temperature=0.0,
                max_tokens=20,
            ),
            timeout=8.0,
        )
        return res.data.get("status") == "ok"
    except Exception as exc:
        logger_msg = f"LLM reachability check failed: {exc}"
        print(logger_msg, file=sys.stderr)
        return False


async def _discover(files: list[str] | None) -> list[Path]:
    attack_files = [f for f in sorted(DEMO_DIR.glob("*.eml"))
                    if any(k in f.name for k in ("injection", "scam", "quishing"))] if DEMO_DIR.exists() else []
    if not attack_files:
        bench_dir = BACKEND_DIR / "data" / "benchmark"
        if bench_dir.exists():
            for c in benchmark.load_manifest(bench_dir / "manifest.csv"):
                if c["expected_label"] in ("DANGEROUS", "SUSPICIOUS"):
                    attack_files.append(bench_dir / c["file"])
    if files:
        wanted = set(files)
        attack_files = [f for f in attack_files if f.name in wanted]
        missing = wanted - {f.name for f in attack_files}
        if missing:
            raise SystemExit(f"Unknown attack file(s): {sorted(missing)}")
    return attack_files


def _rate(executed: int, completed: int) -> float | None:
    return round(executed / completed * 100, 1) if completed else None


async def measure(runs: int = 20, files: list[str] | None = None, shield_on: str = "full",
                  token_budget: int | None = None) -> dict:
    """Run each attack email `runs` times with shield=off and shield=on.

    - A shield=off run whose model call was unavailable is counted as `unavailable`, never as an attack that
      failed; the rate is executed / completed runs.
    - shield_on="rules" runs the protected assistant without model calls (no tokens); "full" uses the LLM.
    - token_budget: stop before the next run once this many tokens were used; the report says so.
    """
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    await connection.init_db()
    attack_files = await _discover(files)

    print(f"Discovered {len(attack_files)} attack test files.")
    print("Checking LLM availability...")
    llm_available = await check_llm_reachability()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = LOCAL_DATA_DIR / f"attack_measurements_{timestamp}.json"

    if not llm_available:
        print("\n[NOTICE] Groq LLM quota is exhausted or unavailable.")
        print("Per project specification, not running with fake models. Marking numbers 'pending, not measured'.\n")
        report = {
            "status": "pending",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": "Real LLM quota exhausted or unavailable; fake models prohibited for measurement.",
            "runs_per_file_target": runs,
            "files_evaluated": [f.name for f in attack_files],
            "results": {
                f.name: {
                    "shield_off_execution_rate": "pending, not measured",
                    "shield_on_execution_rate": "pending, not measured",
                    "status": "pending",
                }
                for f in attack_files
            },
        }
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Pending measurement record written to {out_file}")
        return report

    # Enable vulnerable demo for measurement if LLM is reachable
    orig_allow = settings.ALLOW_VULNERABLE_DEMO
    settings.ALLOW_VULNERABLE_DEMO = True

    results: dict[str, dict] = {}
    tokens = {"shield_off": 0, "shield_on": 0}
    stopped_early = None
    print(f"Beginning live measurement: {runs} runs per attack file (shield=on mode: {shield_on})...")

    try:
        for fpath in attack_files:
            raw_bytes = fpath.read_bytes()
            off = {"runs": 0, "completed": 0, "unavailable": 0, "executed": 0, "tokens": 0}
            on = {"mode": shield_on, "runs": 0, "completed": 0, "unavailable": 0, "executed": 0, "tokens": 0}
            results[fpath.name] = {"shield_off": off, "shield_on": on}
            print(f"\nMeasuring {fpath.name}...")
            for _ in range(runs):
                if token_budget is not None and tokens["shield_off"] + tokens["shield_on"] >= token_budget:
                    stopped_early = f"token budget of {token_budget} reached"
                    break

                meter = groq_client.track_usage()
                res_off = await sandbox_agent.run_vulnerable_assistant(raw_bytes)
                off["runs"] += 1
                off["tokens"] += meter.total_tokens
                tokens["shield_off"] += meter.total_tokens
                if res_off.status == "unavailable":
                    off["unavailable"] += 1
                    if "quota" in (res_off.detail or "") or llm_status.breaker.remaining() > 0:
                        stopped_early = "the model quota ran out"
                        break
                else:
                    off["completed"] += 1
                    off["executed"] += int(bool(res_off.executed and res_off.outbox_entries))

                res_on = await sandbox_agent.run_protected_assistant(raw_bytes, use_llm=shield_on == "full")
                used = ((res_on.verdict or {}).get("llm_usage") or {}).get("total_tokens") or 0
                on["runs"] += 1
                on["tokens"] += used
                tokens["shield_on"] += used
                if res_on.status == "complete":
                    on["completed"] += 1
                    on["executed"] += int(bool(res_on.executed and res_on.outbox_entries))
                else:
                    on["unavailable"] += 1
                await asyncio.sleep(0.5)

            off["executed_rate_pct"] = _rate(off["executed"], off["completed"])
            on["executed_rate_pct"] = _rate(on["executed"], on["completed"])
            print(f"  shield=off executed: {off['executed']}/{off['completed']} completed runs "
                  f"({off['unavailable']} unavailable, {off['tokens']} tokens)")
            print(f"  shield=on  executed: {on['executed']}/{on['completed']} completed runs ({on['tokens']} tokens)")
            if stopped_early:
                print(f"\nStopped early: {stopped_early}")
                break

        report = {
            "status": "completed" if not stopped_early else "partial",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": settings.NANO_MODEL,
            "runs_per_file_target": runs,
            "shield_on_mode": shield_on,
            "token_budget": token_budget,
            "tokens_used": {**tokens, "total": tokens["shield_off"] + tokens["shield_on"]},
            "stopped_early": stopped_early,
            "results": results,
        }
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nMeasurement results saved to {out_file}")
        return report

    finally:
        settings.ALLOW_VULNERABLE_DEMO = orig_allow


def main():
    parser = argparse.ArgumentParser(description="Measure attack success rates in shield=off vs shield=on")
    parser.add_argument("--runs", type=int, default=20, help="Number of runs per file (default: 20)")
    parser.add_argument("--files", nargs="*", help="Only these attack files (names in data/demo_emails)")
    parser.add_argument("--shield-on", choices=("full", "rules"), default="full",
                        help="shield=on with the LLM (full, default) or rules-only (no tokens)")
    parser.add_argument("--token-budget", type=int, default=None,
                        help="Stop before the next run once this many tokens were used")
    args = parser.parse_args()
    asyncio.run(measure(runs=args.runs, files=args.files, shield_on=args.shield_on, token_budget=args.token_budget))


if __name__ == "__main__":
    main()
