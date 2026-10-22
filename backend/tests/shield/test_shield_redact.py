"""PII redaction: typed placeholders, checksums and false-positive guards (30+ cases)."""
import pytest

from shield.redact import Redactor, find, luhn_valid, redact, redact_obj, verhoeff_valid


def aadhaar(prefix11: str) -> str:
    """Complete an 11-digit prefix with the digit that makes it Verhoeff-valid."""
    return next(prefix11 + str(d) for d in range(10) if verhoeff_valid(prefix11 + str(d)))


def bad_aadhaar(prefix11: str) -> str:
    return next(prefix11 + str(d) for d in range(10) if not verhoeff_valid(prefix11 + str(d)))


VALID_AADHAAR = aadhaar("23456789012")
INVALID_AADHAAR = bad_aadhaar("23456789012")


@pytest.mark.parametrize("text, placeholder", [
    (f"Aadhaar {VALID_AADHAAR}", "[AADHAAR]"),
    (f"Aadhaar {VALID_AADHAAR[:4]} {VALID_AADHAAR[4:8]} {VALID_AADHAAR[8:]}", "[AADHAAR]"),
    (f"UID {VALID_AADHAAR[:4]}-{VALID_AADHAAR[4:8]}-{VALID_AADHAAR[8:]}", "[AADHAAR]"),
    ("PAN ABCPE1234F", "[PAN]"),
    ("pan: AAACB1234C", "[PAN]"),
    ("Call 9876543210", "[PHONE]"),
    ("Call +91 98765 43210", "[PHONE]"),
    ("Call +91-9876543210", "[PHONE]"),
    ("Call 0091 9876543210", "[PHONE]"),
    ("Call 098765 43210", "[PHONE]"),
    ("Pay to ravi.k@okaxis now", "[UPI_ID]"),
    ("UPI 9876543210@ybl please", "[UPI_ID]"),
    ("Card 4111 1111 1111 1111", "[CARD]"),
    ("Card 5500-0000-0000-0004", "[CARD]"),
    ("Your OTP is 482913", "[OTP]"),
    ("verification code: 7731", "[OTP]"),
    ("आपका ओटीपी 4829 है", "[OTP]"),
    ("IFSC SBIN0001234", "[IFSC]"),
    ("Mail ravi.kumar@example.com", "[EMAIL]"),
    ("A/c No: 123456789012", "[ACCOUNT_NO]"),
    ("account number 00112233445566", "[ACCOUNT_NO]"),
])
def test_identifiers_are_redacted(text, placeholder):
    out = redact(text)
    assert placeholder in out, out


@pytest.mark.parametrize("text", [
    f"Reference {INVALID_AADHAAR}",          # 12 digits failing Verhoeff is not Aadhaar
    "Order 4111111111111112",                # fails Luhn
    "Meeting on 2026-10-22 at 10:30",
    "Amount ₹15,000 credited",
    "Code ABCDE1234F",                        # 4th letter is not a PAN holder type
    "Branch SBIN1234567",                     # 5th character of an IFSC is always 0
    "PIN code 500081",
    "Tweet by @ravi_k",
    "Serial 1234567890",                      # mobile numbers start with 6-9
    "Invoice INV-2024-0042",
    "Enter the OTP you receive",              # no number
])
def test_false_positive_guards(text):
    assert redact(text) == text


def test_email_is_not_treated_as_upi():
    assert redact("write to ravi@gmail.com") == "write to [EMAIL]"


def test_numbered_placeholders_are_reversible_in_memory_only():
    r = Redactor(numbered=True)
    out = r.redact("Call 9876543210 or 9123456789, again 9876543210")
    assert out == "Call [PHONE_1] or [PHONE_2], again [PHONE_1]"
    assert r.restore(out) == "Call 9876543210 or 9123456789, again 9876543210"
    assert Redactor(numbered=True).restore(out) == out  # another request cannot restore it


def test_redact_obj_walks_nested_structures():
    data = {"from": "a@b.example", "items": ["OTP is 1234", {"phone": "9876543210"}], "n": 5}
    assert redact_obj(data) == {"from": "[EMAIL]", "items": ["OTP is [OTP]", {"phone": "[PHONE]"}], "n": 5}


def test_find_reports_kinds_without_values():
    assert set(find(f"Aadhaar {VALID_AADHAAR}, PAN ABCPE1234F")) == {"AADHAAR", "PAN"}


def test_checksums():
    assert luhn_valid("4111111111111111") and not luhn_valid("4111111111111112")
    assert verhoeff_valid(VALID_AADHAAR) and not verhoeff_valid(INVALID_AADHAAR)
