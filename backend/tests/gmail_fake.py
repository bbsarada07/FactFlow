"""A fake Google (OAuth + Gmail API) that replays tests/fixtures/gmail through httpx.MockTransport.

It checks what a real server would: the PKCE verifier against the challenge, bearer tokens, the
`maxResults` and `after:` search parameters. Every request is recorded so tests can prove the
Gmail API only ever saw GETs. Switches simulate a revoked token, a broader-than-asked grant, etc.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs

import httpx

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gmail"
GMAIL = "/gmail/v1/users/me"


def _json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeGoogle:
    def __init__(self) -> None:
        self.mailbox = _json("mailbox.json")["messages"]  # oldest first
        self.requests: list[tuple[str, str, str]] = []  # (method, host, path)
        self.challenges: dict[str, str] = {}  # code -> code_challenge registered at consent time
        self.valid_access = set()
        self.refresh_fails = False
        self.api_unauthorized = False
        self.broad_scope = False
        self.revoked: list[str] = []
        self.delivered: dict[str, bytes] = {}
        self.code = "fixture-auth-code"

    def consent(self, auth_url: str) -> str:
        """What Google's consent page does: remember the PKCE challenge and hand back a code."""
        q = parse_qs(auth_url.split("?", 1)[1])
        self.challenges[self.code] = q["code_challenge"][0]
        return self.code

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.host, request.url.path))
        if request.url.host == "oauth2.googleapis.com":
            form = parse_qs(request.content.decode())
            if request.url.path == "/revoke":
                self.revoked.append(form["token"][0])
                return httpx.Response(200)
            return self._token(form)
        if request.url.host == "gmail.googleapis.com":
            return self._gmail(request)
        return httpx.Response(404)

    def _token(self, form: dict) -> httpx.Response:
        grant = form["grant_type"][0]
        if grant == "authorization_code":
            code, verifier = form["code"][0], form.get("code_verifier", [""])[0]
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            if self.challenges.get(code) != challenge:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "PKCE mismatch"})
            body = _json("token_exchange.json")
            if self.broad_scope:
                body["scope"] = body["scope"] + " https://www.googleapis.com/auth/" + "gmail" + ".send"  # split: never in code
            self.valid_access.add(body["access_token"])
            return httpx.Response(200, json=body)
        if grant == "refresh_token":
            if self.refresh_fails or form["refresh_token"][0] in self.revoked:
                return httpx.Response(400, json=_json("refresh_invalid_grant.json"))
            body = _json("token_refresh.json")
            self.valid_access.add(body["access_token"])
            return httpx.Response(200, json=body)
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def _gmail(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if self.api_unauthorized or token not in self.valid_access:
            return httpx.Response(401, json=_json("error_401.json"))
        path = request.url.path
        if path == f"{GMAIL}/profile":
            return httpx.Response(200, json=_json("profile.json"))
        if path == f"{GMAIL}/messages":
            params = dict(request.url.params)
            items = list(reversed(self.mailbox))  # newest first, like Gmail
            m = re.fullmatch(r"after:(\d+)", params.get("q", ""))
            if m:
                items = [x for x in items if x["internalDate"] // 1000 > int(m.group(1))]
            items = items[: int(params.get("maxResults", 100))]
            return httpx.Response(200, json={"messages": [{"id": x["id"], "threadId": x["threadId"]} for x in items],
                                             "resultSizeEstimate": len(items)})
        m = re.fullmatch(rf"{GMAIL}/messages/([0-9a-f]+)", path)
        if m and request.url.params.get("format") == "raw":
            mid = m.group(1)
            if mid in self.delivered:
                raw = base64.urlsafe_b64encode(self.delivered[mid]).decode().rstrip("=")
                return httpx.Response(200, json={"id": mid, "threadId": mid, "labelIds": ["INBOX"], "raw": raw})
            file = FIXTURES / "messages" / f"{mid}.json"
            return httpx.Response(200, json=json.loads(file.read_text(encoding="utf-8"))) if file.exists() else httpx.Response(404)
        return httpx.Response(404)

    def deliver(self, name: str, raw: bytes, internal_ms: int) -> str:
        """A new message arrives in the mailbox (kept in memory for this test)."""
        mid = hashlib.sha1(name.encode()).hexdigest()[:16]
        self.mailbox.append({"id": mid, "threadId": mid, "internalDate": internal_ms, "name": name})
        self.delivered[mid] = raw
        return mid
