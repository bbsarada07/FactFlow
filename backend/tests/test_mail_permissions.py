"""What FactFlow may do to a mailbox, enforced by code shape and by the fake Google:

* the only Gmail scopes in the code are gmail.readonly, gmail.send and gmail.modify; full access
  (https://mail.google.com/, which can permanently delete) is never requested and is refused when granted;
* providers have no delete / trash / insert / import / draft methods; the Gmail provider's only writes are
  send, modify_labels and label_id, and its only write endpoints are messages/send, messages/{id}/modify, labels;
* only the outgoing queue (services/mail_sender.py) calls send, and only the mail agent changes labels;
* in a full connect + sync, the mailbox sees no DELETE, PUT or PATCH at all.
"""
import inspect
import re
from pathlib import Path

import pytest

from shield.providers import base, eml, gmail

REPO = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
CODE_SUFFIXES = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml", ".html", ".toml", ".cfg", ".ini"}
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", ".next", "_reference", "fixtures", "tests"}
ALLOWED = {gmail.GMAIL_READONLY_SCOPE, gmail.GMAIL_SEND_SCOPE, gmail.GMAIL_MODIFY_SCOPE}
FORBIDDEN_METHOD = re.compile(r"delete|trash|untrash|insert|import|batch|draft|forward|watch|stop|move", re.IGNORECASE)


def code_files():
    for path in REPO.rglob("*"):
        if path.is_file() and path.suffix in CODE_SUFFIXES and not (set(path.relative_to(REPO).parts) & SKIP_DIRS):
            yield path


def test_only_read_send_and_label_scopes_exist_in_the_code():
    scopes, full_access = {}, []
    for path in code_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for scope in re.findall(r"https://www\.googleapis\.com/auth/gmail[\w.\-/]*", text):
            scopes.setdefault(scope, []).append(str(path.relative_to(REPO)))
        if "https://mail.google.com/" in text:
            full_access.append(str(path.relative_to(REPO)))
    assert set(scopes) <= ALLOWED, scopes
    assert full_access == []


def test_the_consent_url_asks_for_read_send_and_labels_only():
    from urllib.parse import parse_qs, urlsplit

    url = gmail.authorization_url(gmail.OAuthClient("id", "secret", "http://localhost/cb"), "state", "challenge")
    q = parse_qs(urlsplit(url).query)
    assert set(q["scope"][0].split()) == {gmail.GMAIL_MODIFY_SCOPE, gmail.GMAIL_SEND_SCOPE}
    assert "include_granted_scopes" not in q


def test_full_access_or_no_read_access_is_refused_and_read_only_still_works():
    with pytest.raises(gmail.ScopeError):
        gmail._token_set({"access_token": "a", "scope": gmail.GMAIL_MODIFY_SCOPE + " https://mail.google.com/"})
    with pytest.raises(gmail.ScopeError):
        gmail._token_set({"access_token": "a", "scope": gmail.GMAIL_SEND_SCOPE})  # cannot read: useless and odd
    ro = gmail._token_set({"access_token": "a", "scope": gmail.GMAIL_READONLY_SCOPE})
    assert gmail.can_read(ro.scope) and not gmail.can_send(ro.scope) and not gmail.can_label(ro.scope)
    full = gmail._token_set({"access_token": "a", "scope": f"{gmail.GMAIL_MODIFY_SCOPE} {gmail.GMAIL_SEND_SCOPE}"})
    assert gmail.can_send(full.scope) and gmail.can_label(full.scope)


def _public_methods(cls) -> set[str]:
    return {n for n, _ in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")}


def test_providers_cannot_delete_trash_insert_or_draft():
    assert _public_methods(base.MailProvider) == {"list_new", "fetch_raw"}
    for cls in (eml.EmlProvider, gmail.GmailApiProvider):
        methods = _public_methods(cls)
        assert not [m for m in methods if FORBIDDEN_METHOD.search(m)], (cls.__name__, methods)
        assert isinstance(cls.__new__(cls), base.MailProvider)
    writes = _public_methods(gmail.GmailApiProvider) - {"list_new", "fetch_raw", "profile", "list_sent"}
    assert writes == {"send", "modify_labels", "label_id"}
    assert _public_methods(eml.EmlProvider) - {"list_new", "fetch_raw"} == {"add"}  # demo inbox: local only


def test_gmail_write_endpoints_are_send_modify_and_labels_only():
    source = inspect.getsource(gmail)
    assert source.count("http.request(") == 1 and source.count("http.get(") == 0
    posts = re.findall(r'_call\("POST",\s*f?"([^"]+)"', source)
    assert sorted(posts) == ["/labels", "/messages/send", "/messages/{message_id}/modify"], posts
    assert not re.search(r'_call\("(DELETE|PUT|PATCH)"', source)


def test_only_the_outgoing_queue_sends_and_only_the_agent_labels():
    senders, labellers = [], []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(("venv/", "tests/")) or "__pycache__" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"\.send\(raw", text):
            senders.append(rel)
        if re.search(r"\.(modify_labels|label_id)\(", text):
            labellers.append(rel)
    assert senders == ["services/mail_sender.py"], senders
    assert labellers == ["services/mail_agent.py"], labellers


def test_a_full_connect_and_sync_never_deletes_or_rewrites_mail(mail_env):
    from test_mail_agent import connect, sync

    connect(mail_env)
    sync(mail_env)
    mail_env.client.post("/api/mail/gmail/disconnect")
    gmail_calls = [r for r in mail_env.google.requests if r[1] == "gmail.googleapis.com"]
    assert len(gmail_calls) >= 21
    assert {m for m, _, _ in gmail_calls} <= {"GET", "POST"}
    for method, _, path in gmail_calls:
        if method == "POST":
            assert re.search(r"/messages/send$|/messages/[0-9a-f]+/modify$|/labels$", path), path
    for change in mail_env.google.label_changes:  # removing INBOX archives; nothing else is ever removed
        assert set(change["remove"]) <= {"INBOX"}, change
    oauth_calls = [r for r in mail_env.google.requests if r[1] == "oauth2.googleapis.com"]
    assert {p for _, _, p in oauth_calls} <= {"/token", "/revoke"}
