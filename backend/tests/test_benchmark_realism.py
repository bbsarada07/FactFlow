"""The benign bank/shop/government samples come from the brands' real domains, and the same mail from a fake
brand domain (hdfcbank.example, amazon.example, ...) is still flagged: the false-positive fix corrected the test
data, it did not weaken the lookalike detector."""
from pathlib import Path

import pytest

from shield import scan
from shield.email_parser import parse_input

DATA = Path(__file__).resolve().parents[1] / "data" / "benchmark"
REAL_TO_FAKE = {
    "ben_trap05_bank_debit_hdfc": ("hdfcbank.com", "hdfcbank.example"),
    "ben_trap06_bank_credit_sbi": ("sbi.co.in", "sbi.example"),
    "ben_trap07_bank_credit_card_bill": ("icicibank.com", "icicibank.example"),
    "ben_12_ecommerce_delivered": ("amazon.in", "amazon.example"),
    "ben_22_restaurant_table": ("zomato.com", "zomato.example"),
    "ben_24_tax_filing_ack": ("incometax.gov.in", "incometax.example"),
    "ben_27_telecom_bill_invoice": ("airtel.in", "airtel.example"),
}


def label(raw: bytes) -> str:
    return scan.scan_message(parse_input(raw, "upload")).overall.label


@pytest.mark.parametrize("name", sorted(REAL_TO_FAKE))
def test_genuine_brand_mail_is_safe_and_the_same_mail_from_a_fake_domain_is_not(name):
    raw = (DATA / f"{name}.eml").read_bytes()
    real, fake = REAL_TO_FAKE[name]
    assert real.encode() in raw
    assert label(raw) == "SAFE"
    assert label(raw.replace(real.encode(), fake.encode())) != "SAFE"
