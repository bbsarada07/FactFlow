"""find_repeat() / is_fresh(): recognising repeat claims without embeddings."""
from datetime import datetime, timedelta, timezone

from services.registry import Candidate, find_repeat, is_fresh
from services.text_utils import normalize

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
PALGHAR = normalize(
    "ALERT!! Gangs of child kidnappers are moving in villages at night dressed as sadhus and police. "
    "They take children and remove their kidneys. Forward to all groups!"
)
CANDIDATES = [
    Candidate("a", PALGHAR, NOW - timedelta(days=1)),
    Candidate("b", normalize("Drinking cow urine cures coronavirus, doctors confirm"), NOW - timedelta(days=2)),
]


def test_exact_normalised_match():
    m = find_repeat(PALGHAR, CANDIDATES)
    assert m and m.candidate.id == "a" and m.exact and m.score == 100


def test_reworded_forward_matches_fuzzily():
    variant = normalize(
        "Alert: gangs of child kidnappers dressed as police and sadhus are moving in villages at night, "
        "they remove kidneys of children. Forward to all groups"
    )
    m = find_repeat(variant, CANDIDATES)
    assert m and m.candidate.id == "a" and not m.exact and m.score >= 85


def test_unrelated_claim_does_not_match():
    assert find_repeat(normalize("RBI will ban all 10 rupee coins from tomorrow"), CANDIDATES) is None


def test_short_query_is_not_a_subset_match():
    # token_set_ratio alone would score 100 here because the tokens are a subset.
    assert find_repeat(normalize("cow urine"), CANDIDATES) is None


def test_freshness_window():
    assert is_fresh(NOW - timedelta(days=6, hours=23), now=NOW, days=7)
    assert not is_fresh(NOW - timedelta(days=7, minutes=1), now=NOW, days=7)
