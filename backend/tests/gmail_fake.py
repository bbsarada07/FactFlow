"""A fake Google (OAuth + Gmail API) that replays tests/fixtures/gmail through httpx.MockTransport.

It checks what a real server would: the PKCE verifier against the challenge, bearer tokens, the
`maxResults` and `after:` search parameters. Every request is recorded, and every write (sent messages, label
changes) is kept, so tests can prove exactly what FactFlow did to the mailbox. Switches simulate a revoked
token, a broader-than-asked grant, a user who granted read access only, etc.
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
        self.read_only_grant = False  # the user unticked "send" and "labels" on the consent screen
        self.granted_scope = ""
        self.sent: list[dict] = []  # {"raw": bytes, "threadId": str|None}
        self.sent_box: list[dict] = []  # messages the user sent from Gmail: {"id", "internalDate", "raw"}
        self.labels: dict[str, str] = {}  # name -> id
        self.label_changes: list[dict] = []  # {"id", "add", "remove"}

    def consent(self, auth_url: str) -> str:
        """What Google's consent page does: remember the PKCE challenge and hand back a code."""
        q = parse_qs(auth_url.split("?", 1)[1])
        self.challenges[self.code] = q["code_challenge"][0]
        self.granted_scope = "https://www.googleapis.com/auth/gmail.readonly" if self.read_only_grant else q["scope"][0]
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
            body["scope"] = self.granted_scope or body["scope"]
            if self.broad_scope:
                body["scope"] = body["scope"] + " https://mail.google.com/"  # full access: must be refused
            self.valid_access.add(body["access_token"])
            return httpx.Response(200, json=body)
        if grant == "refresh_token":
            if self.refresh_fails or form["refresh_token"][0] in self.revoked:
                return httpx.Response(400, json=_json("refresh_invalid_grant.json"))
            body = _json("token_refresh.json")
            body.pop("scope", None)  # like Google, a refresh may omit the scope; FactFlow keeps the granted one
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
        if path == f"{GMAIL}/messages/send" and request.method == "POST":
            body = json.loads(request.content)
            raw = base64.urlsafe_b64decode(body["raw"] + "=" * (-len(body["raw"]) % 4))
            mid = f"sent{len(self.sent):012d}"
            self.sent.append({"id": mid, "raw": raw, "threadId": body.get("threadId")})
            return httpx.Response(200, json={"id": mid, "threadId": body.get("threadId") or mid, "labelIds": ["SENT"]})
        if path == f"{GMAIL}/labels":
            if request.method == "POST":
                name = json.loads(request.content)["name"]
                self.labels.setdefault(name, f"Label_{len(self.labels) + 1}")
                return httpx.Response(200, json={"id": self.labels[name], "name": name})
            return httpx.Response(200, json={"labels": [{"id": i, "name": n} for n, i in self.labels.items()]})
        m = re.fullmatch(rf"{GMAIL}/messages/([0-9a-f]+)/modify", path)
        if m and request.method == "POST":
            body = json.loads(request.content)
            self.label_changes.append({"id": m.group(1), "add": body.get("addLabelIds", []),
                                       "remove": body.get("removeLabelIds", [])})
            return httpx.Response(200, json={"id": m.group(1)})
        if path == f"{GMAIL}/messages" and dict(request.url.params).get("labelIds") == "SENT":
            items = list(reversed(self.sent_box))
            m = re.fullmatch(r"after:(\d+)", dict(request.url.params).get("q", ""))
            if m:
                items = [x for x in items if x["internalDate"] // 1000 > int(m.group(1))]
            return httpx.Response(200, json={"messages": [{"id": x["id"], "threadId": x["id"]} for x in items]})
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
            sent = next((x for x in self.sent_box if x["id"] == mid), None)
            if sent is not None:
                return httpx.Response(200, json={"id": mid, "threadId": mid, "labelIds": ["SENT"],
                                                 "raw": base64.urlsafe_b64encode(sent["raw"]).decode().rstrip("=")})
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

    def user_sent(self, raw: bytes, internal_ms: int) -> str:
        """The user sends a message from Gmail itself (it shows up in the Sent folder)."""
        mid = hashlib.sha1(raw).hexdigest()[:16]
        self.sent_box.append({"id": mid, "internalDate": internal_ms, "raw": raw})
        return mid
