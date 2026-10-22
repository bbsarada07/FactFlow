"""Authentication headers, sender checks, lookalike domains and link flags."""
import pytest

from shield import domains, phishing
from shield.hidden_content import LinkRef


@pytest.mark.parametrize("header, expected", [
    ("mx.example.com; spf=pass smtp.mailfrom=a.com; dkim=pass header.d=a.com; dmarc=pass", ("pass", "pass", "pass")),
    ("mx.example.com; spf=fail smtp.mailfrom=a.com; dkim=fail; dmarc=fail (p=reject)", ("fail", "fail", "fail")),
    ("mx.example.com; spf=softfail; dkim=neutral; dmarc=none", ("softfail", "none", "none")),
    ("mx.example.com; spf=temperror; dkim=permerror; dmarc=pass", ("unknown", "fail", "pass")),
])
def test_parse_authentication_results(header, expected):
    a = phishing.parse_auth([header], [], dkim_present=True)
    assert (a.spf, a.dkim, a.dmarc) == expected


def test_received_spf_fallback_and_missing_dkim():
    a = phishing.parse_auth(["mx.example.com; dmarc=fail"], ["Fail (domain does not designate sender)"], False)
    assert a.spf == "fail" and a.dkim == "none" and a.dmarc == "fail"


def test_no_headers_is_unknown():
    a = phishing.parse_auth([], [], False)
    assert (a.spf, a.dkim, a.dmarc) == ("unknown", "unknown", "unknown")


def test_reply_to_and_return_path_mismatch():
    s = phishing.check_sender("alerts@bank.example", "Alerts", "help@gmail.com", "bounce@other.example")
    assert s.reply_to_mismatch and s.return_path_mismatch


def test_same_domain_is_not_a_mismatch():
    s = phishing.check_sender("alerts@mail.bank.example", "Alerts", "help@bank.example", "b@bank.example")
    assert not s.reply_to_mismatch and not s.return_path_mismatch


@pytest.mark.parametrize("display, sender", [
    ("SBI Alerts", "alerts@secure-mail.example"),
    ("HDFC Bank Customer Care", "care@hdfc-support.example"),
    ("support@onlinesbi.sbi", "x@evil.example"),
])
def test_display_name_impersonation(display, sender):
    assert phishing.check_sender(sender, display, "", "").display_name_impersonation


@pytest.mark.parametrize("display, sender", [
    ("SBI Alerts", "alerts@sbi.co.in"),
    ("Asha Rao", "asha@example.org"),
])
def test_display_name_not_impersonation(display, sender):
    assert phishing.check_sender(sender, display, "", "").display_name_impersonation is None


def test_cyrillic_display_name_is_flagged():
    s = phishing.check_sender("x@evil.example", "Pаytm Support", "", "")
    assert s.homoglyphs and s.homoglyphs[0].severity == "high"


@pytest.mark.parametrize("host, fragment", [
    ("sbi.co.in.evil.example", "starts with sbi.co.in"),
    ("sbi-kyc-update.com", "contains 'sbi'"),
    ("hdfcbenk.com", "character(s) away from hdfcbank.com"),
    ("irctc.com", "different ending"),
    (domains.normalize_host("sbі.co.in"), "lookalike letters"),  # Cyrillic і
    ("pmkisan-yojana.online", "not a .gov.in"),
])
def test_lookalikes(host, fragment):
    reasons = " | ".join(lk.reason for lk in domains.lookalikes(host))
    assert fragment in reasons, reasons


@pytest.mark.parametrize("host", ["sbi.co.in", "netbanking.hdfcbank.com", "example.org", "uidai.gov.in", "sbi.bank.in",
                                  "taxisolutions.com"])
def test_not_lookalikes(host):
    assert domains.lookalikes(host) == []


@pytest.mark.parametrize("url, flag", [
    ("http://192.168.1.10/login", "ip_address_host"),
    ("https://example.com:8443/pay", "non_standard_port"),
    ("https://www.sbi.co.in@evil.example/login", "at_sign_in_url"),
    ("https://bit.ly/3abcd", "shortener_not_expanded"),
    ("https://a.b.c.d.e.example.com/x", "many_subdomains"),
    ("https://example.com/" + "a" * 220, "very_long_url"),
    ("https://xn--sb-1jc.co.in/", "punycode"),
    ("https://sbi-kyc-update.com/verify", "lookalike_domain"),
])
def test_link_flags(url, flag):
    items, _ = phishing.analyze_links([LinkRef(url, "click", "a")], "")
    assert flag in items[0].flags


def test_urls_in_text_are_found_and_nothing_is_fetched(monkeypatch):
    import httpx

    def boom(*a, **k):
        raise AssertionError("no network access allowed")

    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx, "head", boom)
    items, _ = phishing.analyze_links([], "Pay here: https://bit.ly/x and www.example.org/page.")
    assert {i.url for i in items} == {"https://bit.ly/x", "www.example.org/page"}


def test_clean_link_has_no_flags():
    items, _ = phishing.analyze_links([LinkRef("https://www.irctc.co.in/nget", "Book", "a")], "")
    assert items[0].flags == [] and items[0].severity is None


def test_registrable_domain():
    assert domains.registrable("mail.sbi.co.in") == "sbi.co.in"
    assert domains.registrable("a.b.example.com") == "example.com"
    assert domains.registrable("sbi.co.in.evil.example") == "evil.example"
