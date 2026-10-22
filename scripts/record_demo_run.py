"""Record a real demo run (Phase 4A).

Saves one real successful shield=off attack run (the full transcript and outbox) to
backend/data/demo_recordings/ as JSON, for use as a backup if the live demo misbehaves.
Marked with date, model and 'recorded real run'.
Does NOT fabricate; if no real run is possible yet (e.g. quota exhausted), leaves the script ready.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from config import settings
from database import connection
from models import groq_client
from services import llm_status
from shield import sandbox_agent

DEMO_RECORDINGS_DIR = BACKEND_DIR / "data" / "demo_recordings"
DEMO_EMAIL = BACKEND_DIR / "data" / "demo_emails" / "04_white_on_white_injection.eml"


async def record() -> dict | None:
    DEMO_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    await connection.init_db()

    if not DEMO_EMAIL.exists():
        print(f"Demo email {DEMO_EMAIL} not found.", file=sys.stderr)
        return None

    if not settings.GROQ_API_KEY or llm_status.breaker.remaining() > 0:
        print("[NOTICE] Groq API key is missing or quota is exhausted.")
        print("Per specification: do not fabricate it; script is ready for when quota is available.")
        return None

    orig_allow = settings.ALLOW_VULNERABLE_DEMO
    settings.ALLOW_VULNERABLE_DEMO = True

    try:
        raw_bytes = DEMO_EMAIL.read_bytes()
        print(f"Executing real shield=off run with {settings.NANO_MODEL} on {DEMO_EMAIL.name}...")
        res = await sandbox_agent.run_vulnerable_assistant(raw_bytes)

        if res.status == "unavailable":
            print(f"LLM call was unavailable: {res.detail}")
            print("Per specification: not fabricating. Script ready.")
            return None

        if not res.executed or not res.outbox_entries:
            print("Model did not execute the injected tool call on this attempt.")
            return None

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        record_file = DEMO_RECORDINGS_DIR / f"demo_run_{timestamp}.json"

        data = {
            "type": "recorded real run",
            "date": datetime.now(timezone.utc).isoformat(),
            "model": settings.NANO_MODEL,
            "input_file": DEMO_EMAIL.name,
            "shield": "off",
            "executed": True,
            "summary": res.summary,
            "draft_reply": res.draft_reply,
            "tool_calls": res.tool_calls,
            "outbox_entries": res.outbox_entries,
            "latency_ms": res.latency_ms,
        }

        record_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Successfully recorded real run to: {record_file}")
        return data

    finally:
        settings.ALLOW_VULNERABLE_DEMO = orig_allow


def main():
    asyncio.run(record())


if __name__ == "__main__":
    main()
