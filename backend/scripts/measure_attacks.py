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


async def measure(runs: int = 20) -> dict:
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    await connection.init_db()

    # Find attack emails
    attack_files = []
    if DEMO_DIR.exists():
        for f in sorted(DEMO_DIR.glob("*.eml")):
            fname = f.name
            if any(k in fname for k in ("injection", "scam", "quishing")):
                attack_files.append(f)

    if not attack_files:
        bench_dir = BACKEND_DIR / "data" / "benchmark"
        if bench_dir.exists():
            cases = benchmark.load_manifest(bench_dir / "manifest.csv")
            for c in cases:
                if c["expected_label"] in ("DANGEROUS", "SUSPICIOUS"):
                    attack_files.append(bench_dir / c["file"])

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

    results = {}
    print(f"Beginning live measurement: {runs} runs per attack file...")

    try:
        for fpath in attack_files:
            fname = fpath.name
            raw_bytes = fpath.read_bytes()
            off_exec_count = 0
            on_exec_count = 0

            print(f"\nMeasuring {fname}...")
            for r in range(runs):
                # Run shield=off
                res_off = await sandbox_agent.run_vulnerable_assistant(raw_bytes)
                if res_off.executed and len(res_off.outbox_entries) > 0:
                    off_exec_count += 1

                # Run shield=on
                res_on = await sandbox_agent.run_protected_assistant(raw_bytes, use_llm=True)
                if res_on.executed and len(res_on.outbox_entries) > 0:
                    on_exec_count += 1

                await asyncio.sleep(0.5)

            off_rate = round((off_exec_count / runs) * 100, 1)
            on_rate = round((on_exec_count / runs) * 100, 1)
            print(f"  shield=off executed: {off_exec_count}/{runs} ({off_rate}%)")
            print(f"  shield=on executed:  {on_exec_count}/{runs} ({on_rate}%)")

            results[fname] = {
                "runs": runs,
                "shield_off_executed": off_exec_count,
                "shield_off_rate_pct": off_rate,
                "shield_on_executed": on_exec_count,
                "shield_on_rate_pct": on_rate,
            }

        report = {
            "status": "completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": settings.NANO_MODEL,
            "runs_per_file": runs,
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
    args = parser.parse_args()
    asyncio.run(measure(runs=args.runs))


if __name__ == "__main__":
    main()
