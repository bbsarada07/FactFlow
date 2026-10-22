"""Mail agent end to end over recorded Gmail fixtures and stand-in models (Addendum A2, A3, A1.4).

Every demo email is fetched from (fake) Gmail, analysed, planned, policy-checked and executed or
parked for approval, in strict and in balanced mode. Nothing can reach a real mailbox: outgoing
steps only reach the simulated outbox.
"""
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import openai
import pytest

from standins import OP
from shield.mail_agent import OUTBOX_KIND
from shield.schemas import UnifiedVerdict

FIXTURES = json.load(open(__file__.replace("test_mail_agent.py", "fixtures/gmail/mailbox.json"), encoding="utf-8"))
NAME_BY_ID = {m["id"]: m["name"] for m in FIXTURES["messages"]}
DANGEROUS = {"04_white_on_white_injection", "05_font_size_zero_injection", "06_unicode_tags_injection",
             "07_html_comment_injection", "08_alt_text_injection", "09_fake_kyc_lookalike", "10_digital_arrest_hindi",
             "11_telugu_fake_scheme", "12_upi_collect_scam", "14_mixed_false_claim_and_injection"}
HIDDEN_INJECTION = {"04_white_on_white_injection", "05_font_size_zero_injection", "06_unicode_tags_injection",
                    "07_html_comment_injection", "08_alt_text_injection", "14_mixed_false_claim_and_injection"}
# Messages whose verdict raises a strict-mode signal without being DANGEROUS.
SIGNALLED = {"01_benign_newsletter": "SAFE", "13_quishing_qr": "SUSPICIOUS"}


def gmail_id(name: str) -> str:
    return hashlib.sha1(name.encode()).hexdigest()[:16]


def connect(env) -> None:
    r = env.client.post("/api/mail/gmail/connect", headers=OP)
    assert r.status_code == 200, r.text
    auth_url = r.json()["auth_url"]
    query = parse_qs(urlsplit(auth_url).query)
    assert query["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert query["code_challenge_method"] == ["S256"] and query["access_type"] == ["offline"]
    code = env.google.consent(auth_url)
    cb = env.client.get(f"/api/mail/gmail/callback?code={code}&state={query['state'][0]}", follow_redirects=False)
    assert cb.status_code == 303 and cb.headers["location"].endswith("/inbox?gmail=connected"), cb.headers.get("location")


def set_mode(env, mode: str) -> None:
    r = env.client.put("/api/policy/mode", json={"mode": mode, "confirm": True}, headers=OP)
    assert r.status_code == 200 and r.json()["mode"] == mode


def sync(env, **body) -> dict:
    r = env.client.post("/api/mail/sync", json=body, headers=OP)
    assert r.status_code == 200, r.text
    return r.json()


def tasks_by_name(env) -> dict[str, dict]:
    items = env.client.get("/api/mail/tasks?limit=100", headers=OP).json()["items"]
    out = {}
    for item in items:
        detail = env.client.get(f"/api/mail/tasks/{item['task_id']}", headers=OP).json()
        out[NAME_BY_ID.get(item["message_id"], item["message_id"])] = detail
    return out


def verdict(env, email_id: str) -> UnifiedVerdict:
    r = env.client.get(f"/api/inbox/{email_id}", headers=OP)
    assert r.status_code == 200
    return UnifiedVerdict.model_validate(r.json()["verdict"])


def steps(view: dict, **match) -> list[dict]:
    return [s for s in view["steps"] if all(s.get(k) == v for k, v in match.items())]


# ------------------------------------------------------------------------ all 14 demos

@pytest.mark.parametrize("mode", ["strict", "balanced"])
def test_every_demo_email_gets_a_verdict_and_the_right_agent_behaviour(mail_env, mode):
    env = mail_env
    connect(env)
    if mode == "balanced":
        set_mode(env, "balanced")
    report = sync(env)
    assert report["listed"] == 20 and len(report["new_tasks"]) == 20 and not report["errors"]
    tasks = tasks_by_name(env)
    demos = {n: t for n, t in tasks.items() if not n.startswith("filler")}
    assert len(demos) == 14

    for name, task in demos.items():
        v = verdict(env, task["email_id"])  # schema-valid verdict for every demo email
        assert v.message and v.message.source == "gmail" and v.llm_status.state == "ok"
        states = [t["state"] for t in task["transitions"]]
        assert states[:5] == ["FETCHED", "PARSED", "SCANNED", "PLANNED", "POLICY_CHECKED"], (name, states)
        # Invariants: nothing the message asked for is ever carried out; nothing goes out unapproved.
        for s in task["steps"]:
            if s["origin"] == "untrusted_content":
                assert s["status"] == "blocked" and s["policy"]["rule_id"] in ("P1", "P2"), (name, s)
            if s["task"] in OUTBOX_KIND:
                assert s["status"] != "executed", (name, s)

        if name in DANGEROUS:
            assert v.overall.label == "DANGEROUS"
            assert task["state"] == "DONE" and states[-2:] == ["EXECUTED", "DONE"]
            assert task["quarantined"] and task["reported_phishing"]
            for t in ("summarize", "report_phishing", "quarantine_email"):
                (step,) = steps(task, task=t)
                assert step["status"] == "executed"
                assert ("ran automatically" in (step["notice"] or "")) is (mode == "strict")
            assert not steps(task, task="extract_action_items") and not steps(task, task="draft_reply")
        elif mode == "strict" and name in SIGNALLED:
            assert v.overall.label == SIGNALLED[name]
            assert task["state"] == "AWAITING_APPROVAL"
            (waiting,) = steps(task, status="awaiting_approval")
            assert waiting["task"] == "extract_action_items" and waiting["policy"]["rule_id"] == "S1"
            assert steps(task, task="summarize")[0]["status"] == "executed"  # the warning summary still runs
        else:
            assert v.overall.label in ("SAFE", "SUSPICIOUS")
            assert task["state"] == "DONE" and states[-2:] == ["EXECUTED", "DONE"]  # handled automatically
            assert all(s["status"] == "executed" for s in task["steps"])

        if name in HIDDEN_INJECTION:
            blocked = steps(task, requested_by="message")
            assert blocked and all(s["status"] == "blocked" for s in blocked)

    assert env.client.get("/api/mail/outbox", headers=OP).json()["items"] == []
    pending = env.client.get("/api/approvals?status=pending", headers=OP).json()["items"]
    expected_pending = len(SIGNALLED) if mode == "strict" else 0
    assert len(pending) == expected_pending and all(p["action"] == "extract_action_items" for p in pending)


def test_meeting_invite_is_handled_automatically_with_action_items(mail_env):
    connect(mail_env)
    sync(mail_env)
    task = tasks_by_name(mail_env)["02_benign_meeting_invite"]
    assert task["state"] == "DONE"
    (items,) = steps(task, task="extract_action_items")
    assert items["result"]["meeting"]["when"] == "Thursday 3pm" and items["result"]["items"][0]["task"]


def test_every_transition_is_in_the_audit_log(mail_env):
    connect(mail_env)
    sync(mail_env)
    task = tasks_by_name(mail_env)["04_white_on_white_injection"]
    trail = mail_env.client.get(f"/api/audit?email_id={task['email_id']}&limit=200", headers=OP).json()["items"]
    logged = [i["payload"]["state"] for i in trail if i["event_type"] == "task_state"]
    assert logged == [t["state"] for t in task["transitions"]][1:]  # FETCHED is logged before the email exists
    assert any(i["event_type"] == "step_executed" for i in trail)
    assert mail_env.client.get("/api/audit/verify", headers=OP).json()["ok"] is True


# ------------------------------------------------------------------------ approvals

def _approval_for(env, task: dict) -> dict:
    (waiting,) = steps(task, status="awaiting_approval")
    pending = env.client.get("/api/approvals?status=pending", headers=OP).json()["items"]
    return next(p for p in pending if p["id"] == waiting["approval_id"])


def test_approving_resumes_the_task_and_denying_ends_it(mail_env):
    env = mail_env
    connect(env)
    sync(env)
    tasks = tasks_by_name(env)
    qr, news = tasks["13_quishing_qr"], tasks["01_benign_newsletter"]

    a = _approval_for(env, qr)
    ok = env.client.post(f"/api/approvals/{a['id']}/decision", json={"decision": "approve", "token": a["token"]}, headers=OP)
    assert ok.status_code == 200 and ok.json()["executed"] is True and ok.json()["task_state"] == "DONE"
    again = env.client.post(f"/api/approvals/{a['id']}/decision", json={"decision": "approve", "token": a["token"]}, headers=OP)
    assert again.status_code == 409

    b = _approval_for(env, news)
    no = env.client.post(f"/api/approvals/{b['id']}/decision", json={"decision": "deny", "token": b["token"]}, headers=OP)
    assert no.status_code == 200 and no.json()["executed"] is False and no.json()["step"]["status"] == "denied"
    after = tasks_by_name(env)
    assert after["13_quishing_qr"]["state"] == "DONE" and after["01_benign_newsletter"]["state"] == "DONE"
    assert [t["state"] for t in after["13_quishing_qr"]["transitions"]][-2:] == ["EXECUTED", "DONE"]


def test_user_requested_outgoing_steps_need_approval_and_only_reach_the_simulated_outbox(mail_env):
    env = mail_env
    connect(env)
    sync(env)
    tasks = tasks_by_name(env)
    invite, alert, kyc = tasks["02_benign_meeting_invite"], tasks["03_benign_bank_alert"], tasks["09_fake_kyc_lookalike"]

    fwd = env.client.post(f"/api/mail/tasks/{invite['task_id']}/steps",
                          json={"task": "propose_forward", "target": "friend@elsewhere.example"}, headers=OP).json()
    assert fwd["state"] == "AWAITING_APPROVAL" and steps(fwd, task="propose_forward")[0]["policy"]["rule_id"] == "P4"
    a = _approval_for(env, fwd)
    env.client.post(f"/api/approvals/{a['id']}/decision", json={"decision": "approve", "token": a["token"]}, headers=OP)
    outbox = env.client.get("/api/mail/outbox", headers=OP).json()
    assert outbox["simulated"] is True and len(outbox["items"]) == 1
    assert outbox["items"][0]["kind"] == "forward" and outbox["items"][0]["target"] == "friend@elsewhere.example"

    blocked = env.client.post(f"/api/mail/tasks/{kyc['task_id']}/steps",
                              json={"task": "propose_forward", "target": "friend@elsewhere.example"}, headers=OP).json()
    step = steps(blocked, task="propose_forward")[0]
    assert step["status"] == "blocked" and step["policy"]["rule_id"] == "P3" and blocked["state"] == "DONE"

    link = env.client.post(f"/api/mail/tasks/{alert['task_id']}/steps",
                           json={"task": "propose_open_link", "target": "https://bsbank.example/statement"}, headers=OP).json()
    b = _approval_for(env, link)
    env.client.post(f"/api/approvals/{b['id']}/decision", json={"decision": "deny", "token": b["token"]}, headers=OP)
    assert len(env.client.get("/api/mail/outbox", headers=OP).json()["items"]) == 1  # the denied link never "opened"

    assert env.client.put("/api/policy/allowed-domains", json={"domains": ["trusted.example"], "confirm": True},
                          headers=OP).status_code == 200
    trusted = env.client.post(f"/api/mail/tasks/{alert['task_id']}/steps",
                              json={"task": "propose_forward", "target": "accounts@trusted.example"}, headers=OP).json()
    step = steps(trusted, task="propose_forward", target="accounts@trusted.example")[0]
    # A trusted recipient passes P4, but sending anything out still needs a person (P8, fail closed).
    assert step["status"] == "awaiting_approval" and step["policy"]["rule_id"] == "P8"
    c = _approval_for(env, trusted)
    env.client.post(f"/api/approvals/{c['id']}/decision", json={"decision": "approve", "token": c["token"]}, headers=OP)
    assert len(env.client.get("/api/mail/outbox", headers=OP).json()["items"]) == 2

    bad = env.client.post(f"/api/mail/tasks/{alert['task_id']}/steps", json={"task": "propose_forward"}, headers=OP)
    assert bad.status_code == 422


# ------------------------------------------------------------------- idempotency and limits

def test_each_message_is_one_task_and_a_retry_repeats_nothing(mail_env):
    from services import mail_agent
    from shield.providers.base import RawMessageRef

    env = mail_env
    connect(env)
    first = sync(env)
    second = sync(env)
    assert len(first["new_tasks"]) == 20 and second["new_tasks"] == [] and second["listed"] == 0
    provider = env.client.portal.call(mail_agent.gmail_account.provider)
    again = env.client.portal.call(mail_agent.process, provider, RawMessageRef("gmail", gmail_id("04_white_on_white_injection")))
    assert again is None
    assert env.client.get("/api/mail/tasks?limit=100", headers=OP).json()["total"] == 20


def test_first_connect_takes_the_last_20_then_only_new_mail(mail_env):
    import time

    env = mail_env
    connect(env)
    report = sync(env, mode="rules")
    assert report["listed"] == 20  # of 24 in the mailbox
    names = set(tasks_by_name(env))
    assert {f"filler_{i:02d}" for i in range(4)}.isdisjoint(names)  # the 4 oldest were left alone
    raw = open(__file__.replace("test_mail_agent.py", "../data/demo_emails/02_benign_meeting_invite.eml"), "rb").read()
    new_id = env.google.deliver("new_message", raw.replace(b"demo-02", b"new-02"), int(time.time() * 1000))
    later = sync(env, mode="rules")
    assert later["listed"] == 1 and len(later["new_tasks"]) == 1
    assert env.client.get(f"/api/mail/tasks/{later['new_tasks'][0]}", headers=OP).json()["message_id"] == new_id


def test_per_minute_cap_defers_the_rest_without_losing_them(mail_env, monkeypatch):
    from collections import deque

    from services import mail_agent

    env = mail_env
    monkeypatch.setattr(env.settings, "MAIL_AGENT_MAX_PER_MINUTE", 5)
    connect(env)
    first = sync(env, mode="rules")
    assert len(first["new_tasks"]) == 5 and first["deferred"] == 15
    monkeypatch.setattr(mail_agent, "_recent", deque())
    monkeypatch.setattr(env.settings, "MAIL_AGENT_MAX_PER_MINUTE", 100)
    second = sync(env, mode="rules")  # the cursor did not move, so the deferred mail is still there
    assert len(second["new_tasks"]) == 15 and second["duplicates"] == 5


def test_max_messages_per_sync(mail_env):
    from services import gmail_account
    from shield.providers.gmail import GmailApiProvider

    env = mail_env
    connect(env)
    for i in range(60):
        env.google.deliver(f"bulk_{i}", b"From: a@x.example\nSubject: s\n\nbody", 1_900_000_000_000 + i)
    provider = GmailApiProvider(gmail_account.StoredTokens(), transport=env.google.transport)
    from datetime import datetime, timezone
    refs = env.client.portal.call(provider.list_new, datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert len(refs) == 50


# --------------------------------------------------------------- connection lifecycle

def test_status_never_shows_tokens_and_tokens_are_encrypted_at_rest(mail_env):
    from database import connection
    from database.models import MailAccount
    from services.token_crypto import decrypt, fernet

    env = mail_env
    connect(env)
    status = env.client.get("/api/mail/status", headers=OP).json()
    assert status["gmail"]["status"] == "connected" and status["gmail"]["email_address"] == "factflow-test-inbox@example.com"
    assert "FAKE-" not in json.dumps(status)

    async def row():
        async with connection.session_factory()() as s:
            return await s.scalar(__import__("sqlalchemy").select(MailAccount))

    account = env.client.portal.call(row)
    assert "FAKE-refresh-token-1" not in account.refresh_token_enc
    assert decrypt(fernet(), account.refresh_token_enc) == "FAKE-refresh-token-1"


def test_revoked_token_shows_reconnect_and_never_crashes_the_poller(mail_env, monkeypatch):
    import asyncio

    from services import mail_agent

    env = mail_env
    connect(env)
    env.google.api_unauthorized = True
    env.google.refresh_fails = True
    report = sync(env)
    assert report["reconnect_required"] is True and report["new_tasks"] == []
    status = env.client.get("/api/mail/status", headers=OP).json()["gmail"]
    assert status["status"] == "reconnect_required" and status["reconnect_required"] is True
    assert env.client.post("/api/mail/sync", json={}, headers=OP).status_code == 409

    monkeypatch.setattr(env.settings, "MAIL_POLL_SECONDS", 0.01)

    async def poll_briefly():
        task = asyncio.create_task(mail_agent.poll_forever())
        await asyncio.sleep(0.2)
        assert not task.done()  # still alive after several iterations
        task.cancel()

    env.client.portal.call(poll_briefly)

    env.google.api_unauthorized = env.google.refresh_fails = False
    connect(env)  # reconnect
    assert env.client.get("/api/mail/status", headers=OP).json()["gmail"]["status"] == "connected"
    assert len(sync(env, mode="rules")["new_tasks"]) == 20


def test_expired_access_token_is_refreshed_quietly(mail_env):
    env = mail_env
    connect(env)
    env.google.valid_access.discard("FAKE-access-token-1")  # Google expired it early
    assert len(sync(env, mode="rules")["new_tasks"]) == 20
    assert ("POST", "oauth2.googleapis.com", "/token") in env.google.requests


def test_disconnect_revokes_and_deletes_the_token(mail_env):
    from database import connection
    from database.models import MailAccount

    env = mail_env
    connect(env)
    out = env.client.post("/api/mail/gmail/disconnect", headers=OP).json()
    assert out["revoked"] is True and out["status"] == "disconnected"
    assert env.google.revoked == ["FAKE-refresh-token-1"]

    async def row():
        async with connection.session_factory()() as s:
            return await s.scalar(__import__("sqlalchemy").select(MailAccount))

    account = env.client.portal.call(row)
    assert account.refresh_token_enc is None and account.access_token_enc is None
    assert env.client.get("/api/mail/status", headers=OP).json()["active_provider"] == "eml"


@pytest.mark.parametrize("problem, reason", [("broad_scope", "scope_not_allowed"), ("replayed_state", "auth_failed"),
                                             ("google_error", "denied")])
def test_connect_failures_end_on_an_error_page(mail_env, problem, reason):
    env = mail_env
    auth_url = env.client.post("/api/mail/gmail/connect", headers=OP).json()["auth_url"]
    state = parse_qs(urlsplit(auth_url).query)["state"][0]
    code = env.google.consent(auth_url)
    if problem == "broad_scope":
        env.google.broad_scope = True
        url = f"/api/mail/gmail/callback?code={code}&state={state}"
    elif problem == "replayed_state":
        env.client.get(f"/api/mail/gmail/callback?code={code}&state={state}", follow_redirects=False)
        url = f"/api/mail/gmail/callback?code={code}&state={state}"
    else:
        url = f"/api/mail/gmail/callback?error=access_denied&state={state}"
    r = env.client.get(url, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith(f"gmail=error&reason={reason}")
    if problem == "broad_scope":
        assert env.google.revoked == ["FAKE-refresh-token-1"]  # the broader grant is revoked at once
        assert env.client.get("/api/mail/status", headers=OP).json()["gmail"]["status"] == "disconnected"


def test_connect_needs_the_server_settings(mail_env, monkeypatch):
    monkeypatch.setattr(mail_env.settings, "TOKEN_ENCRYPTION_KEY", "")
    r = mail_env.client.post("/api/mail/gmail/connect", headers=OP)
    assert r.status_code == 503 and "TOKEN_ENCRYPTION_KEY" in r.json()["detail"]


def test_mail_routes_need_the_operator_token(mail_env):
    for method, path in (("GET", "/api/mail/status"), ("POST", "/api/mail/gmail/connect"), ("POST", "/api/mail/sync"),
                         ("POST", "/api/mail/gmail/disconnect"), ("GET", "/api/mail/tasks"), ("GET", "/api/mail/outbox"),
                         ("PUT", "/api/mail/provider")):
        assert mail_env.client.request(method, path, json={}).status_code in (401, 429), path  # 429 after 5 misses


# ------------------------------------------------------------------ demo inbox and degradation

def test_demo_inbox_and_uploads_use_the_same_agent(mail_env):
    env = mail_env
    report = sync(env, mode="rules")  # no Gmail connected: 'auto' uses the demo inbox
    assert report["provider"] == "eml" and len(report["new_tasks"]) == 14
    raw = "Hi Ravi, please reply with the slides for Thursday. Thanks, Asha"
    task = env.client.post("/api/mail/upload", json={"raw": raw}, headers=OP).json()
    assert task["provider"] == "eml" and task["state"] == "DONE"
    assert steps(task, task="draft_reply") == []  # no headers: nobody to reply to


def _rate_limited() -> Exception:
    from models.groq_client import LLMError

    response = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.example/v1/chat/completions"))
    cause = openai.RateLimitError(
        "Rate limit reached for model on tokens per day (TPD): Limit 200000, Used 199849. Please try again in 4m24.8s.",
        response=response, body=None)
    try:
        raise LLMError("Nano model call failed") from cause
    except LLMError as exc:
        return exc


def test_quota_exhaustion_degrades_visibly_and_strict_mode_says_why(mail_env):
    env = mail_env
    env.models.reader_error = _rate_limited()
    meeting = open(__file__.replace("test_mail_agent.py", "../data/demo_emails/02_benign_meeting_invite.eml"), "rb").read()
    task = env.client.post("/api/mail/upload", json={"raw": meeting.decode()}, headers=OP).json()
    v = verdict(env, task["email_id"])
    assert v.llm_status.state == "quota_exhausted" and 260 <= v.llm_status.retry_after_seconds <= 270
    assert "rules-only" in v.llm_status.reason and v.mode == "full"
    (waiting,) = steps(task, status="awaiting_approval")
    assert waiting["task"] == "extract_action_items" and "daily model quota used up" in waiting["policy"]["reason"]
    status = env.client.get("/api/mail/status", headers=OP).json()
    assert status["llm"]["state"] == "quota_exhausted"

    calls_before = env.models.calls["reader"]
    other = env.client.post("/api/mail/upload", json={"raw": meeting.decode().replace("demo-02", "other-02")},
                            headers=OP).json()
    assert env.models.calls["reader"] == calls_before  # the breaker skips the model instead of waiting again
    assert verdict(env, other["email_id"]).llm_status.state == "quota_exhausted"


def test_rules_mode_states_that_the_ai_part_was_not_used(mail_env):
    env = mail_env
    connect(env)
    sync(env, mode="rules")
    task = tasks_by_name(env)["02_benign_meeting_invite"]
    v = verdict(env, task["email_id"])
    assert v.mode == "rules" and v.llm_status.state == "not_used" and v.llm_usage is None
    (items,) = steps(task, task="extract_action_items")
    assert items["result"]["note"].startswith("Action items need the AI reader")


def test_a_step_from_the_message_is_refused_even_if_the_policy_were_bypassed(mail_env):
    from services import mail_agent
    from shield.mail_agent import Step

    env = mail_env
    connect(env)
    sync(env, mode="rules")
    task_id = tasks_by_name(env)["04_white_on_white_injection"]["task_id"]

    async def force():
        from database import connection
        from database.models import MailTask

        async with connection.session_factory()() as s:
            task = await s.get(MailTask, task_id)
            step = Step(task="propose_forward", action="forward_email", target="x@evil.example",
                        origin="untrusted_content", requested_by="message")
            v = await mail_agent._verdict(s, task.email_id)
            await mail_agent._execute(s, task, [step], step, v)

    with pytest.raises(PermissionError):
        env.client.portal.call(force)
