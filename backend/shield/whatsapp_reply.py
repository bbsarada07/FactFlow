"""WhatsApp replies and privacy helpers (Phase 5B/5C). Pure: no config, database or network.

- detect_language: en / hi / te from the script of the text (no model needed).
- hash_sender: the salted SHA-256 that stands in for a phone number everywhere.
- build_reply: at most 900 characters: label, 2-3 reasons, a next step, the helpline for scam-like
  results, and the report link. Built only from fixed templates (shield/config/whatsapp_templates.yml)
  and FactFlow's own findings, never from model output or the message, so a hostile message cannot
  write FactFlow's reply. "limited check" marks a rules-only result.
- strip_message_text: the copy of a verdict that may be stored: the message text and every excerpt
  of it are removed (claims stay: they are already PII-redacted and are kept by the fact-check pipeline).
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from shield import settings
from shield.schemas import UnifiedVerdict

MAX_REPLY_CHARS = 900
LANGUAGES = ("en", "hi", "te")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_TELUGU = re.compile(r"[ఀ-౿]")
_LATIN = re.compile(r"[A-Za-z]")


def templates(language: str) -> dict:
    data = settings.load("whatsapp_templates")
    return data[language if language in LANGUAGES else "en"]


def helplines() -> dict:
    return settings.load("helplines")["india"]


def detect_language(text: str) -> str:
    """The language a reply should use: the script with the most letters (Devanagari is read as Hindi)."""
    counts = {"hi": len(_DEVANAGARI.findall(text or "")), "te": len(_TELUGU.findall(text or "")),
              "en": len(_LATIN.findall(text or ""))}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] else "en"


def normalize_number(number: str) -> str:
    digits = re.sub(r"\D", "", number or "")
    return f"+{digits}" if digits else ""


def hash_sender(salt: str, number: str) -> str:
    """Salted SHA-256 of the sender's number in E.164 form. The number itself is never stored or logged."""
    return hashlib.sha256(f"{salt}:{normalize_number(number)}".encode()).hexdigest()


def actor(sender_hash: str) -> str:
    return f"whatsapp:{sender_hash[:12]}"


# ------------------------------------------------------------------------------- replies


def reason_keys(v: UnifiedVerdict) -> list[str]:
    """Which template reasons apply, strongest first (FactFlow's findings only)."""
    c = v.components
    keys = []
    if c.injection.rule_hits or c.injection.attempted_actions or (c.injection.llm or {}).get("is_injection"):
        keys.append("injection")
    if c.scam.detectors:
        keys.append("scam")
    if c.authenticity.display_name_impersonation or c.authenticity.lookalikes:
        keys.append("impersonation")
    if c.hidden_content.findings:
        keys.append("hidden_content")
    if any(i.flags for i in c.links.items):
        keys.append("links")
    if any(i.verdict in ("FALSE", "MISLEADING") for i in c.claims.items):
        keys.append("false_claim")
    elif any(i.verdict == "UNVERIFIED" for i in c.claims.items):
        keys.append("unverified_claim")
    return keys or ["none_found"]


def _scam_like(v: UnifiedVerdict) -> bool:
    c = v.components
    return v.overall.label != "SAFE" and bool(c.scam.detectors or c.authenticity.display_name_impersonation
                                               or c.authenticity.lookalikes or v.overall.label == "DANGEROUS")


def _fit(parts: list[tuple[str, bool]], limit: int = MAX_REPLY_CHARS) -> str:
    """Join the parts with newlines, keeping every required part and the optional ones that still fit."""
    required = sum(len(p) + 1 for p, req in parts if req)
    budget, out = limit - required, []
    for text, req in parts:
        if req:
            out.append(text)
        elif len(text) + 1 <= budget:
            out.append(text)
            budget -= len(text) + 1
    reply = "\n".join(out)
    return reply if len(reply) <= limit else reply[: limit - 1] + "…"


def build_reply(v: UnifiedVerdict, language: str, report_url: str | None = None, limited: bool = False,
                consent: bool = False, notices: tuple[str, ...] = ()) -> str:
    t = templates(language)
    label = v.overall.label if v.overall.label in t["label"] else "SUSPICIOUS"
    head = t["label"][label] + (f" {t['limited']}" if limited else "")
    names = ", ".join(d.name for d in v.components.scam.detectors[:2])
    reasons = [f"• {t['reasons'][k].format(names=names)}" for k in reason_keys(v)[:3]]
    parts: list[tuple[str, bool]] = []
    if consent:
        parts.append((t["consent"], True))
    parts.append((head, True))
    parts += [(r, i < 2) for i, r in enumerate(reasons)]
    parts += [(t[key], True) for key in notices]
    parts.append((t["next"][label], True))
    if _scam_like(v):
        h = helplines()
        parts.append((t["helpline"].format(helpline=h["cyber_fraud_helpline"], portal=h["cyber_crime_portal"]), True))
    if report_url:
        parts.append((t["report"].format(url=report_url), False))
    return _fit(parts)


def simple_reply(key: str, language: str, consent: bool = False) -> str:
    """A fixed reply (STOP/START confirmations, voice notes, unsupported or too-large input, failures)."""
    t = templates(language)
    return _fit([(t["consent"], True)] * consent + [(t[key], True)])


# ------------------------------------------------------------------------------- privacy


def _host(url: str | None) -> str | None:
    if not url:
        return url
    try:
        return urlsplit(url if "://" in url else f"https://{url}").hostname or "[link]"
    except ValueError:
        return "[link]"


def _excerpts(d: dict) -> list[str]:
    """Every string in the verdict that was copied from the message."""
    c = d["components"]
    found = [d["visible_vs_raw"]["visible_text"], d["visible_vs_raw"]["raw_text"],
             *(s["text"] for s in d["visible_vs_raw"]["diff"]),
             *(f["hidden_text"] for f in c["hidden_content"]["findings"]),
             *(h["evidence"] for h in c["injection"]["rule_hits"]),
             *(a["target"] or "" for a in c["injection"]["attempted_actions"]),
             *(e for s in c["scam"]["detectors"] for e in s["matched_evidence"]),
             *(i["url"] for i in c["links"]["items"]), *(i.get("expanded_to") or "" for i in c["links"]["items"]),
             *(pa.get("target") or "" for pa in d.get("proposed_actions") or [])]
    if d.get("reader_notes"):
        found.append(d["reader_notes"].get("summary") or "")
    if d.get("message"):
        found += [d["message"].get(k) or "" for k in ("subject", "from_addr", "from_display", "reply_to")]
    return sorted({s.strip() for s in found if len(s.strip()) >= 4}, key=len, reverse=True)


def _scrub(obj, patterns: list[re.Pattern]):
    if isinstance(obj, str):
        for p in patterns:
            obj = p.sub("[removed]", obj)
        return obj
    if isinstance(obj, list):
        return [_scrub(x, patterns) for x in obj]
    if isinstance(obj, dict):
        return {k: _scrub(x, patterns) for k, x in obj.items()}
    return obj


def strip_message_text(v: UnifiedVerdict) -> UnifiedVerdict:
    """A copy of the verdict without the message text or excerpts of it (for storing WhatsApp checks).
    Fields that hold message text are emptied; any excerpt still quoted elsewhere (for example in the
    rules-written explanation) is replaced with "[removed]"."""
    d = v.model_dump(mode="json")
    patterns = [re.compile(re.escape(s), re.IGNORECASE) for s in _excerpts(d)]
    d["visible_vs_raw"] = {"visible_text": "", "raw_text": "", "diff": []}
    c = d["components"]
    for f in c["hidden_content"]["findings"]:
        f["hidden_text"] = ""
    for h in c["injection"]["rule_hits"]:
        h["evidence"] = ""
    if c["injection"].get("llm") is not None:
        c["injection"]["llm"] = {k: c["injection"]["llm"].get(k) for k in ("is_injection", "confidence")
                                 if k in c["injection"]["llm"]}
    for a in c["injection"]["attempted_actions"]:
        a["target"] = None
    for s in c["scam"]["detectors"]:
        s["matched_evidence"] = []
    for item in c["links"]["items"]:
        item["url"] = _host(item["url"]) or "[link]"
        item["expanded_to"] = _host(item.get("expanded_to"))
    for pa in d.get("proposed_actions") or []:
        pa["target"] = None
    d["reader_notes"] = None
    if d.get("message"):
        d["message"].update({"subject": "", "from_addr": "", "from_display": "", "reply_to": "", "to": []})
    return UnifiedVerdict.model_validate(_scrub(d, patterns))
