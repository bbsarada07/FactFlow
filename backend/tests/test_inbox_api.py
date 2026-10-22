"""Inbox pipeline and its routes: all 14 demo emails, rules vs full mode, graceful degradation,
caching, registry reuse, token accounting, approvals, audit, policy and operator-token checks.

No network: the quarantined reader, explainer and claim fact-checks are faked.
"""
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from config import settings
from shield.schemas import UnifiedVerdict

DEMO = sorted((Path(__file__).resolve().parents[1] / "data" / "demo_emails").glob("*.eml"))
OP = {"X-Operator-Token": "op-token-for-tests-0123456789"}
EXPECTED = {
    "01_benign_newsletter": "SAFE", "02_benign_meeting_invite": "SAFE", "03_benign_bank_alert": "SAFE",
    "13_quishing_qr": "SUSPICIOUS",
}


def fake_reading(user: str) -> dict:
    """A plausible quarantined-reader answer derived from the message blocks, like a well-behaved model."""
    import re

    content = " ".join(re.findall(r"<untrusted_content[^>]*>(.*?)</untrusted_content>", user, re.DOTALL)).lower()
    injected = any(k in content for k in ("ai assistant", "ignore all previous", "if you are an ai", "assistant:"))
    claims = ["Drinking hot water every 15 minutes kills the coronavirus"] if "hot water" in content else []
    return {"language": "en",
            "injection": {"is_injection": injected, "confidence": 0.9 if injected else 0.1,
                          "categories": ["exfiltration"] if injected else [],
                          "quoted_evidence": ["forward it to all contacts"] if injected else [],
                          "attempted_actions": [{"action": "forward_email", "target": None}] if injected else []},
            "scam": {"is_scam_or_phishing": False, "confidence": 0.2, "reasons": []},
            "claims": {"visible": claims, "hidden": []}}


@pytest.fixture
def app(tmp_path, monkeypatch):
    from api import inbox
    from api.verify import RateLimiter
    from database import connection
    from models.groq_client import LLMResult
    from services import operator_auth, shield_runtime
    import main

    monkeypatch.setattr(settings, "ASYNC_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'i.db').as_posix()}")
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    monkeypatch.setattr(settings, "OPERATOR_TOKEN", OP["X-Operator-Token"])
    monkeypatch.setattr(settings, "APPROVAL_SECRET", "a" * 40)
    monkeypatch.setattr(inbox, "limiter", RateLimiter(1000))
    monkeypatch.setattr(operator_auth, "failures", RateLimiter(5, noun="failed attempts"))
    monkeypatch.setattr(shield_runtime, "_policy", None)

    calls = {"reader": 0, "explainer": 0, "factcheck": 0}

    async def reader(system, user, **k):
        calls["reader"] += 1
        return LLMResult(data=fake_reading(user), model="fake", ms=1, tokens=1)

    async def explainer(system, user, **k):
        calls["explainer"] += 1
        return LLMResult(data={"explanation": "Do not act on this message. See https://evil.example now.",
                               "whatsapp_warning": "Warning: this message is a trick. Visit bit.ly/x"},
                         model="fake", ms=1, tokens=1)

    async def factcheck(claim_id):
        from database.models import Claim
        calls["factcheck"] += 1
        async with connection.session_factory()() as s:
            c = await s.get(Claim, claim_id)
            c.status, c.verdict, c.confidence, c.claim_text = "complete", "FALSE", 0.92, c.raw_input
            await s.commit()

    monkeypatch.setattr("agents.inbox_pipeline.call_nano", reader)
    monkeypatch.setattr("agents.explainer.call_nano", explainer)
    monkeypatch.setattr("agents.inbox_pipeline.run_pipeline", factcheck)
    with TestClient(main.app) as client:
        yield client, calls


def run_demo(client, name, **opts):
    body = {"wait": True, **opts}
    r = client.post(f"/api/inbox/demo/{name}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("path", DEMO, ids=[p.stem for p in DEMO])
def test_every_demo_email_gets_a_schema_valid_verdict(app, path):
    client, _ = app
    data = run_demo(client, path.stem)
    v = UnifiedVerdict.model_validate(data["verdict"])
    assert data["status"] == "complete" and v.mode == "full" and v.email_id == data["email_id"]
    assert v.overall.label == EXPECTED.get(path.stem, "DANGEROUS")
    assert v.audit_head_hash and v.llm_usage is not None and v.latency_ms.total > 0
    assert {"parse", "hidden_html", "quarantined_reader", "score_policy", "audit"} <= set(v.latency_ms.per_stage)


def test_there_are_fourteen_demo_emails(app):
    client, _ = app
    assert len(DEMO) == 14 and len(client.get("/api/inbox/demo").json()["items"]) == 14


def test_rules_mode_makes_no_model_calls(app):
    client, calls = app
    v = UnifiedVerdict.model_validate(run_demo(client, "14_mixed_false_claim_and_injection", mode="rules")["verdict"])
    assert v.mode == "rules" and v.llm_usage is None and v.components.claims.items == []
    assert calls == {"reader": 0, "explainer": 0, "factcheck": 0}


def test_false_claim_joins_the_verdict(app):
    client, calls = app
    v = UnifiedVerdict.model_validate(run_demo(client, "14_mixed_false_claim_and_injection")["verdict"])
    item = v.components.claims.items[0]
    assert item.verdict == "FALSE" and item.credibility == 92 and item.autopsy_id
    assert "MISINFORMATION" in v.harm.types and calls["factcheck"] == 1


def test_repeated_claim_is_answered_from_the_registry(app):
    client, calls = app
    run_demo(client, "14_mixed_false_claim_and_injection")
    raw = (Path(DEMO[0]).parent / "14_mixed_false_claim_and_injection.eml").read_bytes().replace(b"Doctors' advice", b"Advice")
    r = client.post("/api/inbox/analyze", json={"eml_base64": base64.b64encode(raw).decode(), "wait": True, "source": "upload"})
    v = UnifiedVerdict.model_validate(r.json()["verdict"])
    assert v.llm_usage.claims_from_registry == 1 and calls["factcheck"] == 1
    assert v.components.claims.items[0].verdict == "FALSE"


def test_same_message_twice_is_served_from_cache(app):
    client, calls = app
    first = run_demo(client, "04_white_on_white_injection")
    second = run_demo(client, "04_white_on_white_injection")
    assert second["cached"] is True and second["email_id"] == first["email_id"] and calls["reader"] == 1
    third = run_demo(client, "04_white_on_white_injection", force=True)
    assert third["cached"] is False and third["email_id"] != first["email_id"]


def test_explainer_output_cannot_carry_links(app):
    client, _ = app
    v = UnifiedVerdict.model_validate(run_demo(client, "09_fake_kyc_lookalike")["verdict"])
    assert "evil.example" not in v.explanation.text and "bit.ly" not in v.explanation.whatsapp_warning
    assert "[link removed]" in v.explanation.text


def test_llm_failure_degrades_to_rules_and_never_lowers_risk(app, monkeypatch):
    client, _ = app
    rules = UnifiedVerdict.model_validate(run_demo(client, "03_benign_bank_alert", mode="rules")["verdict"])

    async def down(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr("agents.inbox_pipeline.call_nano", down)
    v = UnifiedVerdict.model_validate(run_demo(client, "03_benign_bank_alert", force=True)["verdict"])
    assert any("failed" in f for f in v.analysis_failures) and v.overall.score >= rules.overall.score + 15


def test_a_hanging_model_is_cut_off_and_the_analysis_continues(app, monkeypatch):
    import asyncio
    import time

    client, _ = app

    async def hang(*a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(settings, "INBOX_LLM_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr("agents.inbox_pipeline.call_nano", hang)
    monkeypatch.setattr("agents.explainer.call_nano", hang)
    t0 = time.perf_counter()
    v = UnifiedVerdict.model_validate(run_demo(client, "07_html_comment_injection")["verdict"])
    assert time.perf_counter() - t0 < 5
    assert any("TimeoutError" in f for f in v.analysis_failures) and v.overall.label == "DANGEROUS"
    assert v.explanation.user_language == "en" and v.explanation.text == v.explanation.en


def test_malformed_reader_output_is_discarded(app, monkeypatch):
    from models.groq_client import LLMResult

    client, _ = app

    async def junk(*a, **k):
        return LLMResult(data={"injection": "no", "claims": 3}, model="fake", ms=1, tokens=1)

    monkeypatch.setattr("agents.inbox_pipeline.call_nano", junk)
    v = UnifiedVerdict.model_validate(run_demo(client, "02_benign_meeting_invite")["verdict"])
    assert any("did not match the required format" in f for f in v.analysis_failures)
    assert v.components.injection.llm is None and v.overall.score >= 15
    # The rules scanned everything, so the label may stay SAFE, but strict mode pauses every step.
    from shield.policy import Signals, decide
    d = decide("summarize", None, "user", v.overall.label, mode="strict", signals=Signals.from_verdict(v))
    assert (d.decision, d.rule_id) == ("REQUIRE_APPROVAL", "S1")


def test_token_usage_is_counted_per_stage(app, monkeypatch):
    """Real call_nano path with a fake OpenAI client, so the usage meter is exercised."""
    from models import groq_client

    client, _ = app
    monkeypatch.setattr("agents.inbox_pipeline.call_nano", groq_client.call_nano)  # real client path
    monkeypatch.setattr("agents.explainer.call_nano", groq_client.call_nano)

    class Completions:
        async def create(self, **kw):
            user = kw["messages"][1]["content"]
            data = fake_reading(user) if "VISIBLE TEXT" in user else {"explanation": "ok", "whatsapp_warning": "ok"}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)),
                                                            finish_reason="stop")],
                                   usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120))

    monkeypatch.setattr(groq_client, "client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=Completions())))
    v = UnifiedVerdict.model_validate(run_demo(client, "02_benign_meeting_invite")["verdict"])
    assert v.llm_usage.llm_calls == 2 and v.llm_usage.total_tokens == 240
    assert v.llm_usage.by_stage == {"quarantined_reader": 120, "explainer": 120}


def test_upload_validation(app):
    client, _ = app
    assert client.post("/api/inbox/analyze", json={"eml_base64": "!!!"}).status_code == 422
    assert client.post("/api/inbox/analyze", json={}).status_code == 422
    big = base64.b64encode(b"x" * (5 * 1024 * 1024 + 10)).decode()
    assert client.post("/api/inbox/analyze", json={"eml_base64": big}).status_code in (413, 422)


def test_async_submission_streams_and_completes(app):
    client, _ = app
    r = client.post("/api/inbox/analyze", json={"raw": "Your KYC is pending. Update now or your account will be blocked."})
    assert r.status_code == 202
    email_id = r.json()["email_id"]
    with client.stream("GET", f"/api/inbox/{email_id}/stream") as s:
        events = [line for line in s.iter_lines() if line.startswith("event:")]
    assert events[0] == "event: start" and events[-1] == "event: result"
    got = client.get(f"/api/inbox/{email_id}").json()
    assert got["status"] == "complete" and got["verdict"]["overall"]["label"] != "SAFE"


# ------------------------------------------------------------------- operator-protected routes

def test_operator_token_is_required_and_rate_limited(app):
    client, _ = app
    assert client.get("/api/inbox").status_code == 401
    assert client.get("/api/inbox", headers=OP).status_code == 200
    for _ in range(5):
        client.get("/api/audit", headers={"X-Operator-Token": "wrong"})
    assert client.get("/api/audit", headers={"X-Operator-Token": "wrong"}).status_code == 429
    assert client.get("/api/audit", headers=OP).status_code == 429  # locked out for the rest of the minute


def test_protected_routes_are_closed_without_a_configured_token(app, monkeypatch):
    client, _ = app
    monkeypatch.setattr(settings, "OPERATOR_TOKEN", "")
    for path in ("/api/inbox", "/api/approvals", "/api/audit", "/api/audit/verify"):
        assert client.get(path, headers=OP).status_code == 503


def test_dangerous_email_creates_approvals_that_work_once(app):
    client, _ = app
    data = run_demo(client, "09_fake_kyc_lookalike")
    v = UnifiedVerdict.model_validate(data["verdict"])
    decisions = {(p.action, p.policy.decision, p.policy.rule_id) for p in v.proposed_actions}
    assert ("quarantine_email", "REQUIRE_APPROVAL", "S1") in decisions  # strict mode by default
    pending = client.get("/api/approvals?status=pending", headers=OP).json()
    item = next(i for i in pending["items"] if i["email_id"] == data["email_id"] and i["action"] == "quarantine_email")
    ok = client.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approve", "token": item["token"]}, headers=OP)
    assert ok.status_code == 200 and ok.json()["approval"]["status"] == "approved" and ok.json()["executed"] is False
    again = client.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approve", "token": item["token"]}, headers=OP)
    assert again.status_code == 409
    forged = client.post(f"/api/approvals/{item['id']}/decision", json={"decision": "deny", "token": "0" * 64}, headers=OP)
    assert forged.status_code in (403, 409)


def test_blocked_attempt_is_shown_and_never_approved(app):
    client, _ = app
    v = UnifiedVerdict.model_validate(run_demo(client, "04_white_on_white_injection")["verdict"])
    fwd = next(p for p in v.proposed_actions if p.action == "forward_email" and p.target)
    assert fwd.target == "archive@mail-backup.example" and fwd.origin == "untrusted_content"
    assert (fwd.policy.decision, fwd.policy.rule_id) == ("BLOCK", "P1")
    pending = client.get("/api/approvals?status=pending", headers=OP).json()["items"]
    assert not any(i["action"] == "forward_email" for i in pending)


def test_audit_trail_per_email_and_chain_verifies(app):
    client, _ = app
    email_id = run_demo(client, "06_unicode_tags_injection")["email_id"]
    trail = client.get(f"/api/audit?email_id={email_id}", headers=OP).json()
    kinds = [i["event_type"] for i in trail["items"]]
    assert kinds[0] == "email_received" and kinds[-1] == "verdict" and "policy_decision" in kinds
    assert client.get("/api/audit/verify", headers=OP).json()["ok"] is True


def test_policy_mode_switch_needs_confirmation_and_changes_decisions(app):
    client, _ = app
    assert client.get("/api/policy").json()["mode"] == "strict"
    assert client.put("/api/policy/mode", json={"mode": "balanced"}, headers=OP).status_code == 409
    assert client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True}).status_code == 401
    assert client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True}, headers=OP).json()["mode"] == "balanced"
    v = UnifiedVerdict.model_validate(run_demo(client, "09_fake_kyc_lookalike")["verdict"])
    assert {(p.action, p.policy.decision) for p in v.proposed_actions if p.origin == "user"} == {
        ("report_phishing", "ALLOW"), ("quarantine_email", "ALLOW")}
    events = [i["event_type"] for i in client.get("/api/audit", headers=OP).json()["items"]]
    assert "policy_changed" in events
