"""Build the Gmail API fixtures used by the tests (tests/fixtures/gmail/).

They follow the documented response formats of the Gmail API (users.getProfile, users.messages.list,
users.messages.get with format=raw) and Google's OAuth token endpoint. They were NOT captured from a
live account (none existed yet); docs/GMAIL_SETUP.md lists what to re-check against live Gmail.
All tokens and addresses in them are fake. Run from backend/:

    venv\\Scripts\\python scripts/build_gmail_fixtures.py
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEMO = BACKEND / "data" / "demo_emails"
OUT = BACKEND / "tests" / "fixtures" / "gmail"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
BASE_MS = 1_792_000_000_000  # 2026-10-15, so every message is in the past
FILLERS = 10  # older ordinary messages, so the mailbox holds more than the first-sync limit of 20


def gmail_id(name: str) -> str:
    return hashlib.sha1(name.encode()).hexdigest()[:16]


def filler(i: int) -> bytes:
    m = EmailMessage()
    m["From"] = '"Team Updates" <updates@teamwork.example>'
    m["To"] = "factflow-test-inbox@example.com"
    m["Subject"] = f"Weekly notes #{i}"
    m["Date"] = "Mon, 12 Oct 2026 09:00:00 +0530"
    m["Message-ID"] = f"<filler-{i}@factflow.example>"
    m["Authentication-Results"] = "mx.inbox.example; spf=pass; dkim=pass; dmarc=pass"
    m.set_content(f"Hello team, these are the notes for week {i}. Nothing needs a reply.")
    return m.as_bytes(policy=SMTP)


def main() -> int:
    (OUT / "messages").mkdir(parents=True, exist_ok=True)
    items: list[tuple[str, bytes]] = [(f"filler_{i:02d}", filler(i)) for i in range(FILLERS)]
    items += [(p.stem, p.read_bytes()) for p in sorted(DEMO.glob("*.eml"))]
    index = []
    for n, (name, raw) in enumerate(items):
        mid = gmail_id(name)
        internal = BASE_MS + n * 60_000
        msg = {
            "id": mid, "threadId": mid, "labelIds": ["INBOX", "UNREAD"], "snippet": "",
            "sizeEstimate": len(raw), "historyId": str(500000 + n), "internalDate": str(internal),
            "raw": base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="),
        }
        (OUT / "messages" / f"{mid}.json").write_text(json.dumps(msg, indent=1) + "\n", encoding="utf-8")
        index.append({"id": mid, "threadId": mid, "internalDate": internal, "name": name})
    (OUT / "mailbox.json").write_text(json.dumps({"_note": "newest last; the fake server answers newest first",
                                                  "messages": index}, indent=1) + "\n", encoding="utf-8")
    (OUT / "profile.json").write_text(json.dumps({"emailAddress": "factflow-test-inbox@example.com",
                                                  "messagesTotal": len(items), "threadsTotal": len(items),
                                                  "historyId": str(500000 + len(items))}, indent=1) + "\n", encoding="utf-8")
    tokens = {
        "token_exchange.json": {"access_token": "FAKE-access-token-1", "expires_in": 3599,
                                "refresh_token": "FAKE-refresh-token-1", "scope": SCOPE, "token_type": "Bearer"},
        "token_refresh.json": {"access_token": "FAKE-access-token-2", "expires_in": 3599, "scope": SCOPE,
                               "token_type": "Bearer"},
        "refresh_invalid_grant.json": {"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
        "error_401.json": {"error": {"code": 401, "message": "Request had invalid authentication credentials.",
                                     "status": "UNAUTHENTICATED"}},
    }
    for name, body in tokens.items():
        (OUT / name).write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} messages and {len(tokens) + 2} other fixtures to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
