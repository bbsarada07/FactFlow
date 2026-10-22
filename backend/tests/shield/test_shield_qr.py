"""QR codes in images (quishing)."""
import base64
import io
from email.message import EmailMessage

import segno
from PIL import Image

from shield import qr
from shield.scan import scan_raw

URL = "http://track-parcel-now.example/slot?id=1"


def png(text: str) -> bytes:
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=6, border=4)
    return buf.getvalue()


def test_decodes_a_qr_code():
    assert qr.decode(png(URL)) == [URL]


def test_non_images_and_blank_images_give_nothing():
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, format="PNG")
    assert qr.decode(b"not an image") == [] and qr.decode(buf.getvalue()) == []


def test_oversized_dimensions_are_refused_before_decoding():
    buf = io.BytesIO()
    Image.new("1", (5000, 5000)).save(buf, format="PNG")
    assert qr.decode(buf.getvalue()) == []


def test_data_uri_images():
    uri = "data:image/png;base64," + base64.b64encode(png(URL)).decode()
    assert qr.decode(qr.data_uri_bytes(uri)) == [URL]
    assert qr.data_uri_bytes("https://example.com/a.png") is None


def test_qr_link_in_an_email_is_checked_like_any_link():
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "a@parcel.example", "b@home.example", "Delivery"
    m.set_content("Scan the code to reschedule.")
    m.add_attachment(png("http://sbi-kyc-update.example/login"), maintype="image", subtype="png", filename="qr.png")
    v = scan_raw(m.as_bytes(), "upload")
    item = next(i for i in v.components.links.items if "from_qr_code" in i.flags)
    assert "lookalike_domain" in item.flags and item.severity == "high" and v.input_type == "phishing_or_scam"
