"""normalize() and input_hash(): the canonical form used for repeat detection."""
from services.text_utils import input_hash, normalize


def test_lowercases_and_strips_punctuation():
    assert normalize("ALERT!! Gangs, of KIDNAPPERS...") == "alert gangs of kidnappers"


def test_removes_emoji_and_symbols():
    assert normalize("Look at this video 😍🔥 #viral ₹500") == "look at this video viral 500"


def test_strips_urls():
    assert normalize("Read this https://example.com/a?b=1 and www.test.in/x now") == "read this and now"


def test_collapses_whitespace():
    assert normalize("  many \n\n spaces\tand\ttabs ") == "many spaces and tabs"


def test_keeps_indic_vowel_signs():
    # Devanagari matras are combining marks; they must survive or Hindi text is mangled.
    assert normalize("गौमूत्र से कोरोना ठीक!") == "गौमूत्र से कोरोना ठीक"


def test_idempotent():
    once = normalize("Forward to ALL groups!!! 🙏 https://x.co/1")
    assert normalize(once) == once


def test_hash_ignores_formatting_differences():
    assert input_hash("Cow urine cures COVID!!") == input_hash("cow urine cures covid 🙏")
    assert input_hash("cow urine cures covid") != input_hash("garlic cures covid")
