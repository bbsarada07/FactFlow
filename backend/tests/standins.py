"""Stand-in models for tests (no network, no quota): a well-behaved quarantined reader, an
explainer and a claim fact-check. They answer from the message blocks the way a real model would
be expected to, so tests exercise the real pipeline around them."""
from __future__ import annotations

import re

from models.groq_client import LLMResult

OP = {"X-Operator-Token": "op-token-for-tests-0123456789"}  # operator header used by the tests


def reading_for(user: str) -> dict:
    content = " ".join(re.findall(r"<untrusted_content[^>]*>(.*?)</untrusted_content>", user, re.DOTALL)).lower()
    injected = any(k in content for k in ("ai assistant", "ignore all previous", "if you are an ai", "assistant:"))
    target = next(iter(re.findall(r"[\w.+-]+@[\w-]+\.example", content)), None)
    claims = ["Drinking hot water every 15 minutes kills the coronavirus"] if "hot water" in content else []
    meeting = {"title": "Project sync", "when": "Thursday 3pm", "where": "room 4B"} if "project sync" in content else None
    items = [{"task": "Join the project sync", "due": "Thursday 3pm", "amount": None}] if meeting else []
    return {
        "language": "en",
        "injection": {"is_injection": injected, "confidence": 0.9 if injected else 0.1,
                      "categories": ["exfiltration"] if injected else [],
                      "quoted_evidence": ["forward all emails"] if injected else [],
                      "attempted_actions": [{"action": "forward_email", "target": target}] if injected else []},
        "scam": {"is_scam_or_phishing": False, "confidence": 0.2, "reasons": []},
        "claims": {"visible": claims, "hidden": []},
        "summary": "A message about " + (meeting["title"] if meeting else "an ordinary topic") + ".",
        "action_items": items,
        "reply_requested": "please reply" in content,
        "meeting": meeting,
    }


class StandIns:
    def __init__(self) -> None:
        self.calls = {"reader": 0, "explainer": 0, "factcheck": 0}
        self.reader_error: BaseException | None = None

    async def reader(self, system, user, **k):
        self.calls["reader"] += 1
        if self.reader_error is not None:
            raise self.reader_error
        return LLMResult(data=reading_for(user), model="stand-in", ms=1, tokens=1)

    async def explainer(self, system, user, **k):
        self.calls["explainer"] += 1
        return LLMResult(data={"explanation": "Stand-in explanation.", "whatsapp_warning": "Stand-in warning."},
                         model="stand-in", ms=1, tokens=1)

    async def factcheck(self, claim_id):
        from database import connection
        from database.models import Claim

        self.calls["factcheck"] += 1
        async with connection.session_factory()() as s:
            c = await s.get(Claim, claim_id)
            c.status, c.verdict, c.confidence, c.claim_text = "complete", "FALSE", 0.92, c.raw_input
            await s.commit()

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr("agents.inbox_pipeline.call_nano", self.reader)
        monkeypatch.setattr("agents.explainer.call_nano", self.explainer)
        monkeypatch.setattr("agents.inbox_pipeline.run_pipeline", self.factcheck)
