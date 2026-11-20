"""Accounts end to end, with real sign-in (no default test user): Google sign-in against a fake Google,
sessions, CSRF, extension tokens, admin-only routes, and the core promise: one user can never read, list, stream,
decide or change anything that belongs to another user.
"""
import base64
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.real_auth

CLIENT_ID = "fake-client.apps.googleusercontent.com"


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


class FakeGoogleLogin:
    """Google's token endpoint: returns an ID token for whichever identity the test chose."""

    def __init__(self) -> None:
        self.identity = {}
        self.forms = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com" and request.url.path == "/token":
            self.forms.append(parse_qs(request.content.decode()))
            claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "exp": int(time.time()) + 600,
                      "email_verified": True, **self.identity}
            return httpx.Response(200, json={"id_token": f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.sig",
                                             "access_token": "unused"})
        return httpx.Response(404)

    @property
    def transport(self):
        return httpx.MockTransport(self.handle)


@pytest.fixture
def env(db_url, monkeypatch):
    from types import SimpleNamespace

    from cryptography.fernet import Fernet

    import main
    from api import auth as auth_api
    from api import inbox
    from api import verify as verify_api
    from api.verify import RateLimiter
    from config import settings
    from database import connection
    from services import google_login, shield_runtime

    for name, value in {
        "ASYNC_DATABASE_URL": db_url, "GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": "FAKE-secret",
        "SECRET_KEY": "s" * 40, "FRONTEND_URL": "http://testserver", "ENVIRONMENT": "development",
        "APPROVAL_SECRET": "a" * 40, "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(), "INBOX_USE_LLM": False,
        "ALLOWED_EMAILS": "", "ADMIN_EMAILS": "admin@example.com", "MAIL_POLL_ENABLED": False,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    monkeypatch.setattr(shield_runtime, "_policy", None)
    monkeypatch.setattr(inbox, "limiter", RateLimiter(1000))
    monkeypatch.setattr(verify_api, "limiter", RateLimiter(1000))
    monkeypatch.setattr(auth_api, "login_limiter", RateLimiter(1000))
    monkeypatch.setattr(verify_api, "dispatch", lambda claim_id: "inprocess")  # no model calls
    google = FakeGoogleLogin()
    monkeypatch.setattr(google_login, "HTTP_TRANSPORT", google.transport)
    with TestClient(main.app) as first:
        yield SimpleNamespace(app=main.app, first=first, google=google, settings=settings)


def browser(env, **kwargs) -> TestClient:
    """A separate browser (its own cookie jar) on the same running app and event loop as env.first."""
    c = TestClient(env.app, **kwargs)
    c.portal = env.first.portal  # the database engine belongs to this loop
    return c


def sign_in(env, email: str, sub: str | None = None, client: TestClient | None = None) -> TestClient:
    """Run the real sign-in flow in a fresh browser (cookie jar). Returns a client that sends the CSRF header."""
    c = client or browser(env)
    env.google.identity = {"sub": sub or f"sub-{email}", "email": email, "name": email.split("@")[0]}
    start = c.get("/api/auth/google/login?next=/shield", follow_redirects=False)
    assert start.status_code == 303
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    back = c.get(f"/api/auth/google/callback?code=fake-code&state={state}", follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"] == "/shield", back.headers.get("location")
    me = c.get("/api/auth/me").json()
    c.headers["X-CSRF-Token"] = me["csrf_token"]
    return c


def analyse(c: TestClient, demo: str = "02_benign_meeting_invite") -> dict:
    r = c.post(f"/api/inbox/demo/{demo}", json={"mode": "rules", "wait": True})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------------------ sign-in


def test_sign_in_sets_a_secure_session_and_me_answers(env):
    c = browser(env)
    assert c.get("/api/auth/me").status_code == 401
    assert c.get("/api/inbox").status_code == 401
    env.google.identity = {"sub": "g-1", "email": "Asha@Example.com", "name": "Asha"}
    start = c.get("/api/auth/google/login?next=/settings", follow_redirects=False)
    url = urlsplit(start.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com" and q["scope"] == ["openid email profile"]
    assert q["redirect_uri"] == ["http://testserver/api/auth/google/callback"] and q["code_challenge_method"] == ["S256"]
    back = c.get(f"/api/auth/google/callback?code=c&state={q['state'][0]}", follow_redirects=False)
    cookies = back.headers.get_list("set-cookie")
    session = next(x for x in cookies if x.startswith("ff_session="))
    assert "HttpOnly" in session and "SameSite=lax" in session
    assert back.headers["location"] == "/settings"
    me = c.get("/api/auth/me").json()
    assert me["user"]["email"] == "asha@example.com" and me["user"]["role"] == "user" and me["csrf_token"]
    assert env.google.forms[-1]["code_verifier"] and env.google.forms[-1]["client_secret"] == ["FAKE-secret"]


def test_the_session_value_is_never_stored(env):
    from database import connection
    from database.models import UserSession
    from sqlalchemy import select

    c = sign_in(env, "store@example.com")
    cookie = c.cookies.get("ff_session")

    async def rows():
        async with connection.session_factory()() as s:
            return [r.id for r in (await s.scalars(select(UserSession))).all()]

    ids = env.first.portal.call(rows)
    assert cookie not in ids and len(ids) == 1 and len(ids[0]) == 64  # only the SHA-256


@pytest.mark.parametrize("tamper", ["no_cookie", "wrong_state", "forged_cookie"])
def test_callback_needs_the_signed_state_from_the_same_browser(env, tamper):
    c = browser(env)
    env.google.identity = {"sub": "g-2", "email": "x@example.com"}
    start = c.get("/api/auth/google/login", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    if tamper == "no_cookie":
        c = browser(env)
    elif tamper == "wrong_state":
        state = "not-the-state"
    else:
        forged = c.cookies.get("ff_oauth").rsplit(".", 1)[0] + ".forged"
        c.cookies.clear()
        c.cookies.set("ff_oauth", forged)
    back = c.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert back.headers["location"] == "/login?error=expired"
    assert c.get("/api/auth/me").status_code == 401


def test_unverified_or_unlisted_emails_are_refused(env, monkeypatch):
    c = browser(env)
    env.google.identity = {"sub": "g-3", "email": "nope@example.com", "email_verified": False}
    start = c.get("/api/auth/google/login", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    back = c.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert back.headers["location"] == "/login?error=email_not_verified"

    monkeypatch.setattr(env.settings, "ALLOWED_EMAILS", "team@example.com, lead@example.com")
    env.google.identity = {"sub": "g-4", "email": "outsider@example.com"}
    start = c.get("/api/auth/google/login", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    back = c.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert back.headers["location"] == "/login?error=not_allowed"
    sign_in(env, "lead@example.com")  # listed: fine


@pytest.mark.parametrize("target", ["//evil.example/x", "https://evil.example", "/\\evil.example", "javascript:alert(1)"])
def test_next_can_only_be_a_path_on_this_site(env, target):
    c = browser(env)
    env.google.identity = {"sub": "g-5", "email": "next@example.com"}
    start = c.get("/api/auth/google/login", params={"next": target}, follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    back = c.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert back.headers["location"] == "/"


def test_logout_ends_the_session(env):
    c = sign_in(env, "bye@example.com")
    old = c.cookies.get("ff_session")
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401
    again = browser(env)
    again.cookies.set("ff_session", old)
    assert again.get("/api/inbox").status_code == 401  # the old cookie is dead server-side too


# --------------------------------------------------------------------------------------------- CSRF


def test_changes_need_the_csrf_token(env):
    c = sign_in(env, "csrf@example.com")
    token = c.headers.pop("X-CSRF-Token")
    assert c.post("/api/inbox/demo/02_benign_meeting_invite", json={"mode": "rules"}).status_code == 403
    assert c.put("/api/policy/mode", json={"mode": "balanced", "confirm": True}).status_code == 403
    assert c.post("/api/inbox/demo/02_benign_meeting_invite", json={"mode": "rules"},
                  headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert c.get("/api/inbox").status_code == 200  # reading needs no CSRF token
    assert c.post("/api/inbox/demo/02_benign_meeting_invite", json={"mode": "rules", "wait": True},
                  headers={"X-CSRF-Token": token}).status_code == 200


# ------------------------------------------------------------------------------------------ isolation


def test_one_user_never_sees_another_users_data(env):
    a = sign_in(env, "asha@example.com")
    b = sign_in(env, "bala@example.com")

    # A analyses a message, runs a fact-check, and gives the agent a suspicious email (approval pending)
    email = analyse(a)
    claim = a.post("/api/verify", json={"text": "The RBI has banned all UPI payments above Rs 500."}).json()
    task = a.post("/api/mail/upload", json={"raw": open(
        __file__.replace("test_accounts.py", "../data/demo_emails/13_quishing_qr.eml"), encoding="utf-8").read(),
        "mode": "rules"}).json()
    approvals = a.get("/api/approvals?status=pending").json()["items"]

    # A sees all of it
    assert [i["email_id"] for i in a.get("/api/inbox").json()["items"]][-1] == email["email_id"]
    assert a.get(f"/api/inbox/{email['email_id']}").status_code == 200
    assert a.get(f"/api/result/{claim['request_id']}").status_code in (200, 202)
    assert a.get(f"/api/mail/tasks/{task['task_id']}").status_code == 200

    # B sees none of it: lists are empty and every id answers 404, exactly like a missing one
    assert b.get("/api/inbox").json()["items"] == []
    assert b.get(f"/api/inbox/{email['email_id']}").status_code == 404
    assert b.get(f"/api/inbox/{email['email_id']}/stream").status_code == 404
    assert b.get(f"/api/result/{claim['request_id']}").status_code == 404
    assert b.get(f"/api/status/{claim['request_id']}").status_code == 404
    assert b.get(f"/api/stream/{claim['request_id']}").status_code == 404
    assert b.get(f"/api/v/{claim['slug']}").status_code == 404
    assert claim["request_id"] not in [i["request_id"] for i in b.get("/api/history?limit=100").json()["items"]]
    assert b.get("/api/mail/tasks").json()["items"] == []
    assert b.get(f"/api/mail/tasks/{task['task_id']}").status_code == 404
    assert b.post(f"/api/mail/tasks/{task['task_id']}/steps", json={"task": "draft_reply"}).status_code == 404
    assert b.get("/api/mail/outbox").json()["items"] == []
    assert b.get("/api/approvals").json()["items"] == []
    for ap in approvals:
        r = b.post(f"/api/approvals/{ap['id']}/decision", json={"decision": "approve", "token": ap["token"]})
        assert r.status_code == 404  # even with A's valid single-use token
    assert all(i["payload"].get("email_id") != email["email_id"] for i in b.get("/api/audit?limit=200").json()["items"])
    assert b.get("/api/audit?everyone=true&limit=200").json()["total"] == b.get("/api/audit?limit=200").json()["total"]

    # B's identical message is analysed as B's own, never served from A's cache
    mine = analyse(b)
    assert mine["email_id"] != email["email_id"] and mine["cached"] is False
    assert mine["email_id"] not in [i["email_id"] for i in a.get("/api/inbox").json()["items"]]


def test_a_fact_check_is_never_answered_from_another_users_history(env):
    from database import connection
    from database.models import Claim

    a = sign_in(env, "first@example.com")
    b = sign_in(env, "second@example.com")
    text = "A new 2000 rupee note with a GPS chip is being issued next month."
    first = a.post("/api/verify", json={"text": text}).json()

    async def complete():
        async with connection.session_factory()() as s:
            c = await s.get(Claim, first["request_id"])
            c.status, c.verdict, c.confidence = "complete", "FALSE", 0.9
            await s.commit()

    env.first.portal.call(complete)
    assert a.post("/api/verify", json={"text": text}).json()["cached"] is True  # A's own repeat
    theirs = b.post("/api/verify", json={"text": text}).json()
    assert theirs["cached"] is False and theirs["request_id"] != first["request_id"]


def test_policy_and_mail_settings_are_per_user(env):
    a = sign_in(env, "strict-a@example.com")
    b = sign_in(env, "strict-b@example.com")
    assert a.put("/api/policy/mode", json={"mode": "balanced", "confirm": True}).json()["mode"] == "balanced"
    assert a.put("/api/mail/provider", json={"provider": "eml"}).status_code == 200
    assert b.get("/api/policy").json()["mode"] == "strict"
    assert b.get("/api/mail/status").json()["provider_setting"] == "auto"


def test_demo_inbox_uploads_stay_with_the_uploader(env):
    a = sign_in(env, "up-a@example.com")
    b = sign_in(env, "up-b@example.com")
    before = b.get("/api/mail/status").json()["demo_inbox"]["messages"]
    a.post("/api/mail/upload", json={"raw": "Subject: private\n\nmy own upload", "mode": "rules"})
    assert b.get("/api/mail/status").json()["demo_inbox"]["messages"] == before
    report = b.post("/api/mail/sync", json={"mode": "rules"}).json()
    assert all("private" not in (t.get("subject") or "") for t in b.get("/api/mail/tasks?limit=100").json()["items"])
    assert report["provider"] == "eml"


# --------------------------------------------------------------------------------- extension, admin


def test_extension_token_works_without_csrf_and_can_be_revoked(env):
    a = sign_in(env, "ext@example.com")
    made = a.post("/api/account/extension-tokens", json={"label": "Chrome"})
    assert made.status_code == 201
    token = made.json()["token"]
    assert token.startswith("ffx_") and made.json()["prefix"] == token[:10]
    ext = browser(env, headers={"Authorization": f"Bearer {token}"})
    r = ext.post("/api/verify", json={"text": "Drinking hot water cures every virus, says a forward."})
    assert r.status_code == 202, r.text
    assert a.get(f"/api/result/{r.json()['request_id']}").status_code in (200, 202)  # it is the same user's check
    # the extension cannot manage the account
    assert ext.post("/api/account/extension-tokens", json={}).status_code == 403
    assert ext.put("/api/policy/mode", json={"mode": "balanced", "confirm": True}).status_code == 403
    listed = a.get("/api/account/extension-tokens").json()["items"]
    assert [t["id"] for t in listed] == [made.json()["id"]] and "token" not in listed[0]
    assert a.delete(f"/api/account/extension-tokens/{made.json()['id']}").status_code == 200
    assert ext.get("/api/inbox").status_code == 401
    b = sign_in(env, "other@example.com")
    assert b.delete(f"/api/account/extension-tokens/{made.json()['id']}").status_code == 404


def test_only_admins_run_the_benchmark(env):
    user = sign_in(env, "plain@example.com")
    assert user.post("/api/benchmark/run", json={"mode": "rules", "sample_size": 2}).status_code == 403
    admin = sign_in(env, "admin@example.com")
    assert admin.get("/api/auth/me").json()["user"]["role"] == "admin"
    assert admin.post("/api/benchmark/run", json={"mode": "rules", "sample_size": 2}).status_code == 200


def test_whatsapp_link_code_is_six_digits_and_replaced_on_request(env):
    a = sign_in(env, "wa@example.com")
    first = a.post("/api/account/whatsapp/link-code").json()
    second = a.post("/api/account/whatsapp/link-code").json()
    assert re.fullmatch(r"\d{6}", first["code"]) and second["message"] == f"LINK {second['code']}"
    assert a.get("/api/account/whatsapp").json() == {"linked_numbers": 0}


def test_a_gmail_connect_state_only_works_for_the_user_who_started_it(env):
    from services import gmail_account
    from shield.providers.base import ProviderAuthError

    state = gmail_account.states.create("verifier", "user-a")

    async def finish_as_b():
        await gmail_account.finish_connect(state, "code", "user-b")

    with pytest.raises(ProviderAuthError):
        env.first.portal.call(finish_as_b)
    assert gmail_account.states.pop(state) is None  # used up by the failed attempt


def test_every_data_route_refuses_anonymous_requests(env):
    c = browser(env)
    for method, path in [
        ("GET", "/api/history"), ("GET", "/api/stats"), ("GET", "/api/registry"), ("GET", "/api/incidents"),
        ("POST", "/api/verify"), ("GET", "/api/result/x"), ("GET", "/api/stream/x"), ("GET", "/api/v/x"),
        ("GET", "/api/inbox"), ("POST", "/api/inbox/analyze"), ("GET", "/api/inbox/demo"), ("GET", "/api/inbox/x"),
        ("GET", "/api/mail/status"), ("POST", "/api/mail/gmail/connect"), ("POST", "/api/mail/sync"),
        ("GET", "/api/mail/tasks"), ("GET", "/api/mail/outbox"), ("GET", "/api/approvals"), ("GET", "/api/audit"),
        ("GET", "/api/audit/verify"), ("GET", "/api/policy"), ("PUT", "/api/policy/mode"),
        ("GET", "/api/sandbox/outbox"), ("GET", "/api/benchmark/latest"), ("GET", "/api/account/extension-tokens"),
    ]:
        assert c.request(method, path, json={}).status_code == 401, (method, path)
    for path in ("/health", "/api/config", "/api/accuracy"):
        assert c.get(path).status_code == 200, path
