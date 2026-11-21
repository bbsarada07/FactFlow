"""Checks on mail going OUT: deterministic, no model. Used before the agent sends anything on its own, before a
message written in FactFlow is sent, and on mail the user already sent from Gmail (to warn about leaks).

A finding never sends or blocks anything by itself: the caller decides (an automatic reply with any finding
waits for the user instead; a message the user wrote needs their confirmation).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from shield import domains, redact

FINANCIAL_KINDS = {
    "OTP": "a one-time password (OTP)", "CARD": "a card number", "ACCOUNT_NO": "a bank account number",
    "AADHAAR": "an Aadhaar number", "PAN": "a PAN number", "UPI_ID": "a UPI ID", "IFSC": "an IFSC code",
}
SECRET_PATTERNS = (
    ("aws key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("API key", re.compile(r"\b(?:sk|pk|rk)-(?:live-|test-|proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("password", re.compile(r"(?i)\b(?:password|passwd|pwd|passcode|pin)\s*(?:is|:|=)\s*\S{4,}")),
)
# Words that make a message about money, credentials or account changes: never a "routine" reply.
SENSITIVE_TOPIC = re.compile(
    r"(?i)(₹|\brs\.?\s?\d|\binr\b|\$\s?\d|\bpayment|\bpay\b|\btransfer|\bwire\b|\bbank|\bupi\b|\binvoice|\brefund"
    r"|\bgift ?card|\botp\b|\bpassword|\bcredential|\blogin\b|\bsign[- ]?in\b|\baccount (?:number|details)"
    r"|\bkyc\b|\baadhaar|\bpan card|\bsalary|\bloan\b|\bcrypto|\bbitcoin|\bwallet|\bconfidential|\bsecret\b)"
)
_ADDR = re.compile(r"[^\s<>,;\"']+@[^\s<>,;\"']+")


@dataclass(frozen=True)
class Finding:
    kind: str  # financial | secret | lookalike_recipient | brand_lookalike
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def addresses(text: str) -> list[str]:
    return [a.strip().lower() for a in _ADDR.findall(text or "")]


def _domain(addr: str) -> str:
    return addr.rpartition("@")[2].lower().strip(".")


def check(text: str, recipients: list[str] | None = None, known: set[str] | None = None) -> list[Finding]:
    """Findings for an outgoing message: financial or identity numbers, secrets, and a recipient whose domain
    looks like (but is not) one the user already writes to, or like a known brand."""
    out: list[Finding] = []
    kinds = sorted(set(redact.find(text or "")) & set(FINANCIAL_KINDS))
    for k in kinds:
        out.append(Finding("financial", f"The message contains {FINANCIAL_KINDS[k]}."))
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text or ""):
            out.append(Finding("secret", f"The message seems to contain a {name}."))
    known_domains = {_domain(a) for a in (known or set()) if "@" in a}
    for addr in recipients or []:
        dom = _domain(addr)
        if not dom or dom in known_domains:
            continue
        near = sorted(k for k in known_domains if k != dom and domains.levenshtein(dom, k, limit=2) <= 2)
        if near:
            out.append(Finding("lookalike_recipient",
                               f"{addr} looks like your contact domain {near[0]} but is different. Check the address."))
        for la in domains.lookalikes(dom):
            out.append(Finding("brand_lookalike", f"{addr} imitates {la.brand if hasattr(la, 'brand') else 'a known brand'}."))
            break
    return out


def sensitive_topic(text: str) -> bool:
    """True when a message is about money, credentials, identity or account changes."""
    return bool(SENSITIVE_TOPIC.search(text or ""))


NO_REPLY = re.compile(r"(?i)^(?:no-?reply|do-?not-?reply|donotreply|mailer-daemon|postmaster|bounce[s]?|notifications?"
                      r"|alerts?|newsletter|news|marketing|info|updates?)[@+.-]")


def is_automated_sender(addr: str) -> bool:
    """Addresses that should never get an automatic reply (no-reply, notifications, newsletters, bounces)."""
    return bool(NO_REPLY.search((addr or "").strip()))
