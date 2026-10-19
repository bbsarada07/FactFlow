"""redact_pii(): phone numbers, e-mails and account handles are removed before storage."""
import pytest

from services.text_utils import redact_pii


@pytest.mark.parametrize(
    "text",
    [
        "Call 9876543210 now",
        "Call +91 98765 43210 now",
        "Call +91-9876543210 now",
        "Call +919876543210 now",
        "Call 0091 9876543210 now",
        "Call 09876543210 now",
        "Call 98765-43210 now",
        "Ref 12345678901234 now",
    ],
)
def test_phone_numbers_are_redacted(text):
    out = redact_pii(text)
    assert "[phone]" in out
    assert not any(ch.isdigit() for ch in out.replace("[phone]", ""))


def test_email_and_handles_are_redacted():
    out = redact_pii("Mail rumours@example.com or DM @some_user_99 today")
    assert "rumours@example.com" not in out and "@some_user_99" not in out
    assert "[email]" in out and "[handle]" in out


@pytest.mark.parametrize(
    "text",
    ["In 2020, 3 people died", "Government gives ₹5000 to 1,00,000 people", "Call 100 or 112", "Dated 16/04/2020"],
)
def test_ordinary_numbers_are_kept(text):
    assert redact_pii(text) == text
