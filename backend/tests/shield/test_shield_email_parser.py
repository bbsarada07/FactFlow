"""Email intake: headers, parts, attachments, limits, plain text."""
import hashlib
import io
from email.message import EmailMessage

import pytest
from pypdf import PdfWriter

from shield.email_parser import (
    MAX_ATTACHMENTS,
    MAX_BODY_CHARS,
    EmailInputError,
    looks_like_rfc822,
    parse_email,
    parse_input,
)


def build(html: str | None = "<p>Hello</p>", plain: str | None = "Hello", attachments=()) -> bytes:
    m = EmailMessage()
    m["From"] = '"Asha Rao" <asha@example.org>'
    m["To"] = "ravi@example.com"
    m["Reply-To"] = "help@example.net"
    m["Subject"] = "Monthly statement ₹"
    m["Message-ID"] = "<abc@example.org>"
    m["Authentication-Results"] = "mx.example.com; spf=pass smtp.mailfrom=example.org; dkim=pass; dmarc=pass"
    m["Received"] = "from mail.example.org by mx.example.com"
    if plain is not None:
        m.set_content(plain)
    if html is not None:
        if plain is None:
            m.set_content(html, subtype="html")
        else:
            m.add_alternative(html, subtype="html")
    for name, data, mtype in attachments:
        main, sub = mtype.split("/")
        m.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return m.as_bytes()


def test_headers_and_parts():
    pe = parse_email(build(), "upload")
    assert pe.from_addr == "asha@example.org" and pe.from_display == "Asha Rao"
    assert pe.reply_to == "help@example.net" and pe.to == ["ravi@example.com"]
    assert pe.subject == "Monthly statement ₹" and pe.message_id == "<abc@example.org>"
    assert "spf=pass" in pe.authentication_results[0] and pe.received
    assert pe.text_plain.strip() == "Hello" and "<p>Hello</p>" in pe.text_html
    assert pe.has_alternative and pe.from_domain == "example.org"


def test_attachment_metadata_and_text_extraction():
    pe = parse_email(build(attachments=[("note.txt", b"plain words inside", "text/plain"),
                                        ("photo.png", b"\x89PNG\r\n\x1a\nxxxx", "image/png")]))
    names = {a.filename: a for a in pe.attachments}
    assert names["note.txt"].text == "plain words inside"
    assert names["photo.png"].text is None
    assert names["photo.png"].sha256 == hashlib.sha256(b"\x89PNG\r\n\x1a\nxxxx").hexdigest()
    assert names["photo.png"].summary()["size"] == 12


def test_pdf_metadata_is_extracted_without_rendering():
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.add_metadata({"/Subject": "hidden prose in the document properties of this pdf file"})
    buf = io.BytesIO()
    w.write(buf)
    pe = parse_email(build(attachments=[("doc.pdf", buf.getvalue(), "application/pdf")]))
    assert pe.attachments[0].metadata["Subject"].startswith("hidden prose")


def test_rejects_oversized_input():
    with pytest.raises(EmailInputError):
        parse_email(b"x" * (5 * 1024 * 1024 + 1))


def test_rejects_too_many_attachments():
    atts = [(f"a{i}.bin", b"x", "application/octet-stream") for i in range(MAX_ATTACHMENTS + 1)]
    with pytest.raises(EmailInputError):
        parse_email(build(attachments=atts))


def test_long_body_is_truncated_and_reported():
    pe = parse_email(build(html=None, plain="a" * (MAX_BODY_CHARS + 500)))
    assert pe.body_truncated and len(pe.text_plain) == MAX_BODY_CHARS


def test_plain_paste_has_no_headers():
    pe = parse_input("Your KYC is pending. Click the link now.")
    assert not pe.has_headers and pe.text_plain.startswith("Your KYC")


def test_raw_source_paste_is_parsed_as_email():
    pe = parse_input(build().decode("utf-8", errors="replace"))
    assert pe.has_headers and pe.from_addr == "asha@example.org"


@pytest.mark.parametrize("text, expected", [
    (b"From: a@b.c\nSubject: hi\n\nbody", True),
    (b"Subject: great news\nFrom: x@y.z\n\nhello", True),
    (b"Subject is great: we won the match", False),
    (b"Note: meeting at 5\nAgenda: budget", False),
])
def test_header_detection(text, expected):
    assert looks_like_rfc822(text) is expected


def test_latin1_body_is_decoded():
    raw = (b"From: a@example.org\nTo: b@example.org\nSubject: x\nContent-Type: text/plain; charset=iso-8859-1\n\n"
           b"caf\xe9 au lait")
    assert "café" in parse_email(raw).text_plain
