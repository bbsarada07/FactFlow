"""Small pieces of the inbox pipeline: explainer link filter, DNS record check."""
import asyncio

import pytest

from agents.explainer import _no_links
from services import dns_checks


@pytest.mark.parametrize("text", [
    "Visit https://evil.example/login now", "Go to www.evil.example", "write to help@evil.example",
    "open bit.ly/3xYz", "see sbi-kyc-update.in today",
])
def test_explainer_output_has_links_removed(text):
    out = _no_links(text)
    assert "[link removed]" in out and "evil" not in out and "bit.ly" not in out and "sbi-kyc" not in out


def test_plain_sentences_are_kept():
    text = "यह संदेश खतरनाक है। Do not share your OTP. Rs. 2,500 was mentioned."
    assert _no_links(text) == text


def test_dns_check_flags_missing_records(monkeypatch):
    async def txt(name):
        return {"bank.example": ["v=spf1 include:_spf.bank.example -all"], "_dmarc.bank.example": []}.get(name)

    monkeypatch.setattr(dns_checks, "_txt", txt)
    assert asyncio.run(dns_checks.sender_records("bank.example")) == [("bank.example publishes no DMARC record", "low")]


def test_dns_lookup_failures_give_no_signal(monkeypatch):
    async def fail(name):
        return None

    monkeypatch.setattr(dns_checks, "_txt", fail)
    assert asyncio.run(dns_checks.sender_records("bank.example")) == []
