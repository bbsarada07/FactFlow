"""FactFlow can only read mail: no Gmail scope but gmail.readonly anywhere in the code, no send /
delete / modify method on any provider, and nothing but GETs ever reach the Gmail API."""
import inspect
import re
from pathlib import Path

from shield.providers import base, eml, gmail

REPO = Path(__file__).resolve().parents[2]
CODE_SUFFIXES = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml", ".html", ".toml", ".cfg", ".ini"}
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", ".next", "_reference", "fixtures"}
READONLY = "https://www.googleapis.com/auth/gmail.readonly"
FORBIDDEN_METHOD = re.compile(r"send|delete|trash|untrash|modify|insert|import|batch|label|draft|move|archive|"
                              r"forward|reply|write|update|patch|remove|create|watch|stop", re.IGNORECASE)


def code_files():
    for path in REPO.rglob("*"):
        if path.is_file() and path.suffix in CODE_SUFFIXES and not (set(path.relative_to(REPO).parts) & SKIP_DIRS):
            if path.resolve() != Path(__file__).resolve():
                yield path


def test_gmail_readonly_is_the_only_google_mail_scope_in_the_code():
    scopes, full_access = {}, []
    for path in code_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for scope in re.findall(r"https://www\.googleapis\.com/auth/[\w.\-/]+", text):
            scopes.setdefault(scope, []).append(str(path.relative_to(REPO)))
        if "https://mail.google.com/" in text:  # the full-access Gmail scope
            full_access.append(str(path.relative_to(REPO)))
    assert set(scopes) == {READONLY}, scopes
    assert full_access == []
    assert gmail.GMAIL_READONLY_SCOPE == READONLY


def test_the_consent_url_asks_for_readonly_only():
    from urllib.parse import parse_qs, urlsplit

    url = gmail.authorization_url(gmail.OAuthClient("id", "secret", "http://localhost/cb"), "state", "challenge")
    q = parse_qs(urlsplit(url).query)
    assert q["scope"] == [READONLY] and "include_granted_scopes" not in q


def test_a_broader_grant_is_refused():
    import pytest

    with pytest.raises(gmail.ScopeError):
        gmail._token_set({"access_token": "a", "scope": READONLY + " https://www.googleapis.com/auth/gmail." + "modify"})


def _public_methods(cls) -> set[str]:
    return {n for n, _ in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")}


def test_providers_have_no_send_delete_or_modify_methods():
    assert _public_methods(base.MailProvider) == {"list_new", "fetch_raw"}
    for cls in (eml.EmlProvider, gmail.GmailApiProvider):
        methods = _public_methods(cls)
        assert {"list_new", "fetch_raw"} <= methods
        assert not [m for m in methods if FORBIDDEN_METHOD.search(m)], (cls.__name__, methods)
        assert isinstance(cls.__new__(cls), base.MailProvider)


def test_gmail_provider_code_only_issues_gets_to_the_gmail_api():
    source = inspect.getsource(gmail)
    for verb in ("post", "put", "patch", "delete", "request"):
        calls = re.findall(rf"http\.{verb}\(\s*([^,)]+)", source)
        if verb == "post":
            assert calls == ["url"]  # only _post_form, used for the OAuth token and revoke endpoints
        else:
            assert calls == [], (verb, calls)
    assert source.count("http.get(") == 1 and "f\"{GMAIL_API}{path}\"" in source


def test_only_gets_reach_the_gmail_api_in_a_full_connect_and_sync(mail_env):
    from test_mail_agent import connect, sync

    connect(mail_env)
    sync(mail_env)
    mail_env.client.post("/api/mail/gmail/disconnect", headers={"X-Operator-Token": "op-token-for-tests-0123456789"})
    gmail_calls = [r for r in mail_env.google.requests if r[1] == "gmail.googleapis.com"]
    oauth_calls = [r for r in mail_env.google.requests if r[1] == "oauth2.googleapis.com"]
    assert len(gmail_calls) >= 21 and {m for m, _, _ in gmail_calls} == {"GET"}
    assert {p for _, _, p in oauth_calls} <= {"/token", "/revoke"}
    assert all(r[1] in ("gmail.googleapis.com", "oauth2.googleapis.com") for r in mail_env.google.requests)
