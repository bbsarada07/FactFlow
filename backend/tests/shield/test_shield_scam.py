"""India-specific scam detectors: one or more positives per detector, plus benign messages."""
import pytest

from shield.scam_patterns import detectors, scan


def ids(text: str) -> set[str]:
    return {h.id for h in scan(text)}


@pytest.mark.parametrize("text, detector", [
    ("This is CBI. You are under digital arrest. Stay on the video call.", "SC-01"),
    ("आप डिजिटल अरेस्ट में हैं, कॉल मत काटिए", "SC-01"),
    ("Your parcel from Mumbai contains drugs and fake passports.", "SC-01"),
    ("Your KYC is pending. Update now or your account will be blocked.", "SC-02"),
    ("PAN not linked with Aadhaar, link before deadline or penalty", "SC-02"),
    ("Enter your UPI PIN to receive Rs 5,000 cashback", "SC-03"),
    ("पैसे पाने के लिए अपना पिन डालें", "SC-03"),
    ("Congratulations! You have won Rs 25 lakh in the KBC lottery. Pay processing fee.", "SC-04"),
    ("PM Kisan: register here to claim Rs 6000, click the link", "SC-05"),
    ("सरकार सभी को मुफ्त ₹5000 दे रही है, लिंक पर क्लिक करें", "SC-05"),
    ("Work from home job, pay registration fee of Rs 999 to start", "SC-06"),
    ("Earn Rs 3000 per day by liking YouTube videos on Telegram", "SC-06"),
    ("Your electricity connection will be disconnected tonight. Call the officer.", "SC-07"),
    ("Your parcel is on hold at customs. Pay the clearance fee of Rs 49.", "SC-08"),
    ("Double your money in 30 days with our crypto plan", "SC-09"),
    ("Join our stock tips group on WhatsApp for guaranteed returns", "SC-09"),
    ("Please share the OTP you just received to complete verification", "SC-10"),
    ("OTP batao jaldi", "SC-10"),
    ("OTP cheppandi please", "SC-10"),
    ("Download AnyDesk and share the code with our agent", "SC-11"),
    ("Act now! Final notice: legal action within 24 hours", "SC-12"),
    ("Do not tell anyone about this call, keep it secret", "SC-13"),
    ("किसी को मत बताना", "SC-13"),
])
def test_detectors_fire(text, detector):
    assert detector in ids(text), (detector, ids(text))


@pytest.mark.parametrize("text", [
    "Never share your OTP, PIN or CVV with anyone. SBI never asks for these.",
    "Your account statement for October is ready to view in net banking.",
    "Your electricity bill of Rs 1,200 is due on 25 October.",
    "We are hiring a backend engineer. Apply on our careers page.",
    "Police issued an arrest warrant for the suspect, the newspaper reported.",
    "Your Amazon order has been shipped and will arrive on Friday.",
    "Do not tell anyone your PIN.",
])
def test_benign_messages_do_not_fire_high_severity(text):
    high = [h for h in scan(text) if h.severity in ("high", "critical")]
    assert high == [], high


def test_detector_ids_are_unique_and_cover_required_types():
    all_ids = [d.id for d in detectors()]
    assert len(all_ids) == len(set(all_ids)) and len(all_ids) >= 13


def test_evidence_is_returned():
    hit = next(h for h in scan("Download AnyDesk and share the code") if h.id == "SC-11")
    assert hit.matched_evidence and "anydesk" in hit.matched_evidence[0]
