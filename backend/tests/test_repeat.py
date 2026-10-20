"""Regression tests for repeat-detection false positives on short texts."""
from datetime import datetime, timezone

from services.registry import Candidate, find_repeat
from services.text_utils import normalize, redact_pii

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def candidate(text: str, cid: str = "stored") -> Candidate:
    return Candidate(cid, normalize(text), NOW)


def test_short_forward_does_not_match_pension_claim_text():
    stored = candidate("Free pension money from the government is available via a WhatsApp forward")
    assert find_repeat("forward this to phone or phone now", [stored]) is None


def test_short_forward_does_not_match_pension_forward_sharing_placeholder():
    # The pair that actually matched in production (score 85.7): both redacted inputs
    # contained [phone], which normalises to the shared word "phone".
    stored = candidate(redact_pii("Forward this to 9876543210 for free pension money from the government."))
    query = normalize(redact_pii("Forward this to +91 98765 43210 or 9876543210 now"))
    assert query == "forward this to phone or phone now"
    assert find_repeat(query, [stored]) is None


def test_same_claim_with_different_punctuation_still_matches():
    stored = candidate("Free pension money from the government is available via a WhatsApp forward.")
    query = normalize("FREE pension money -- from the government, is available via a WhatsApp forward!!!")
    m = find_repeat(query, [stored])
    assert m is not None and m.candidate.id == "stored" and m.score == 100


def test_reworded_long_forward_with_placeholder_still_matches():
    stored = candidate(redact_pii(
        "Government is giving free pension money to every senior citizen, call 9876543210 to register before Sunday"
    ))
    query = normalize(redact_pii(
        "Govt is giving free pension money to every senior citizen! Call +91 91234 56789 to register before Sunday"
    ))
    m = find_repeat(query, [stored])
    assert m is not None and not m.exact and m.score >= 85
