"""WhatsApp webhook end to end (Phase 5): signature gate, pipeline, reply, privacy and abuse controls.

Uses recorded-format webhook fixtures (tests/fixtures/whatsapp), a fake Twilio REST API (httpx.MockTransport)
and the stand-in models from the mail-agent tests; no network and no real Twilio account.
"""
import hashlib
import hmac
import io
import json
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest
from loguru import logger
from sqlalchemy import select, text

from config import settings
from shield.providers.whatsapp import twilio_signature
from shield.whatsapp_reply import MAX_REPLY_CHARS, templates
from standins import OP

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "whatsapp"
URL = "https://factflow.example/api/whatsapp/webhook"
TOKEN = "test-twilio-auth-token-not-real"
SENDER = "+919999900001"
SENDER_DIGITS = "9999900001"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    return buf.getvalue()


class FakeTwilio:
    """Twilio's REST API as far as FactFlow uses it: send a message, fetch inbound media (via a CDN redirect)."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.image = png()
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/Messages.json"):
            self.sent.append(dict(parse_qsl(request.content.decode())))
            return httpx.Response(201, json={"sid": f"SM{len(self.sent):032d}"})
        if request.method == "GET" and request.url.host == "api.twilio.com" and "/Media/" in request.url.path:
            return httpx.Response(302, headers={"location": "https://media.twiliocdn.com/fake/image.png"})
        if request.method == "GET" and request.url.host == "media.twiliocdn.com":
            return httpx.Response(200, content=self.image, headers={"content-type": "image/png"})
        return httpx.Response(404)


@pytest.fixture
def wa(mail_env, monkeypatch):
    from api.verify import RateLimiter
    from services import whatsapp_service

    for name, value in {
        "WHATSAPP_PROVIDER": "twilio", "TWILIO_ACCOUNT_SID": "AC" + "0" * 32, "TWILIO_AUTH_TOKEN": TOKEN,
        "TWILIO_WHATSAPP_FROM": "+14155238886", "PUBLIC_BASE_URL": "https://factflow.example",
        "WHATSAPP_HASH_SALT": "test-salt-not-secret-0123", "FRONTEND_URL": "https://app.factflow.example",
        "META_APP_SECRET": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    twilio = FakeTwilio()
    monkeypatch.setattr(whatsapp_service, "HTTP_TRANSPORT", twilio.transport)
    monkeypatch.setattr(whatsapp_service, "sender_limiter", RateLimiter(10, noun="WhatsApp checks", window=3600))
    mail_env.twilio = twilio
    return mail_env


def post(env, params: dict, signature: str | None = None, url: str = URL):
    sig = twilio_signature(TOKEN, url, params) if signature is None else signature
    return env.client.post("/api/whatsapp/webhook", data=params, headers={"X-Twilio-Signature": sig} if sig else {})


def with_id(params: dict, n: int, body: str | None = None) -> dict:
    out = {**params, "MessageSid": f"SM{n:032d}", "SmsMessageSid": f"SM{n:032d}", "SmsSid": f"SM{n:032d}"}
    return out if body is None else {**out, "Body": body}


def audit_events(env, event_type: str) -> list[dict]:
    async def read():
        from database import connection
        from database.models import AuditLog

        async with connection.session_factory()() as s:
            rows = (await s.scalars(select(AuditLog).where(AuditLog.event_type == event_type).order_by(AuditLog.seq))).all()
            return [{"actor": r.actor, **(r.payload_json if isinstance(r.payload_json, dict) else json.loads(r.payload_json))}
                    for r in rows]

    return env.client.portal.call(read)


def checks(env) -> list[dict]:
    async def read():
        from database import connection
        from database.models import WhatsAppCheck

        async with connection.session_factory()() as s:
            return [r.to_dict() for r in (await s.scalars(select(WhatsAppCheck).order_by(WhatsAppCheck.created_at))).all()]

    return env.client.portal.call(read)


# ------------------------------------------------------------------------------ signature gate


def test_valid_signature_is_accepted_and_the_reply_goes_to_the_sender_only(wa):
    resp = post(wa, fixture("twilio_text.json"))
    assert resp.status_code == 200 and "<Response>" in resp.text
    [sent] = wa.twilio.sent
    assert sent["To"] == f"whatsapp:{SENDER}" and sent["From"] == "whatsapp:+14155238886"
    reply = sent["Body"]
    t = templates("en")
    assert len(reply) <= MAX_REPLY_CHARS
    assert t["consent"] in reply  # first message from this sender
    assert t["label"]["DANGEROUS"] in reply or t["label"]["SUSPICIOUS"] in reply
    assert "1930" in reply and "https://app.factflow.example/inbox/" in reply
    [check] = checks(wa)
    assert check["delivery"] == "sent" and check["input_type"] == "text" and check["label"] in ("DANGEROUS", "SUSPICIOUS")


@pytest.mark.parametrize("case", ["tampered body", "wrong url", "missing header", "other token"])
def test_bad_signatures_are_refused_with_403_before_any_processing(wa, monkeypatch, case):
    from services import whatsapp_service

    handled = []
    monkeypatch.setattr(whatsapp_service, "handle", lambda msg: handled.append(msg))
    params = fixture("twilio_text.json")
    good = twilio_signature(TOKEN, URL, params)
    if case == "tampered body":
        resp = post(wa, {**params, "Body": params["Body"] + " (edited)"}, signature=good)
    elif case == "wrong url":
        resp = post(wa, params, signature=twilio_signature(TOKEN, "https://other.example/api/whatsapp/webhook", params))
    elif case == "missing header":
        resp = post(wa, params, signature="")
    else:
        resp = post(wa, params, signature=twilio_signature("another-token", URL, params))
    assert resp.status_code == 403
    assert handled == [] and wa.twilio.sent == [] and checks(wa) == []


def test_reordered_params_still_validate(wa):
    params = fixture("twilio_text.json")
    sig = twilio_signature(TOKEN, URL, params)
    resp = post(wa, dict(reversed(list(params.items()))), signature=sig)
    assert resp.status_code == 200 and len(wa.twilio.sent) == 1


def test_missing_settings_refuse_with_a_clear_log_line_and_the_app_still_runs(wa, monkeypatch):
    from api import whatsapp as wa_api

    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "")
    monkeypatch.setattr(settings, "WHATSAPP_HASH_SALT", "")
    monkeypatch.setattr(wa_api, "_warned", set())
    logs: list[str] = []
    sink = logger.add(lambda m: logs.append(str(m)), level="DEBUG")
    try:
        resp = post(wa, fixture("twilio_text.json"), signature="anything")
    finally:
        logger.remove(sink)
    assert resp.status_code == 503
    line = next(m for m in logs if "WhatsApp webhook refused" in m)
    assert "TWILIO_AUTH_TOKEN" in line and "WHATSAPP_HASH_SALT" in line
    assert wa.client.get("/health").status_code == 200


def test_there_is_no_signature_bypass_setting():
    assert not [name for name in type(settings).model_fields if "WHATSAPP" in name and ("SKIP" in name or "BYPASS" in name)]
    assert not [name for name in type(settings).model_fields if "TWILIO" in name and ("SKIP" in name or "BYPASS" in name)]


# ------------------------------------------------------------------------------ replies


def test_without_send_credentials_the_reply_is_a_dry_run_in_the_audit_log(wa, monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "")
    assert post(wa, fixture("twilio_text.json")).status_code == 200
    assert wa.twilio.sent == []
    [entry] = audit_events(wa, "whatsapp_reply")
    assert entry["delivery"] == "dry_run" and "DRY RUN" in entry["note"] and entry["reply"]
    assert checks(wa)[0]["delivery"] == "dry_run"


def test_consent_notice_only_on_the_first_message(wa):
    post(wa, fixture("twilio_text.json"))
    post(wa, with_id(fixture("twilio_text.json"), 77, "Is this true? Drinking hot water every 15 minutes kills the coronavirus"))
    first, second = (s["Body"] for s in wa.twilio.sent)
    consent = templates("en")["consent"]
    assert consent in first and consent not in second


def test_a_retried_webhook_is_answered_once(wa):
    params = fixture("twilio_text.json")
    post(wa, params)
    post(wa, params)
    assert len(wa.twilio.sent) == 1 and len(checks(wa)) == 1


def test_voice_notes_are_not_supported_yet(wa):
    post(wa, fixture("twilio_voice.json"))
    [sent] = wa.twilio.sent
    assert templates("en")["voice"] in sent["Body"]
    assert checks(wa)[0]["input_type"] == "voice"


@pytest.mark.parametrize("language, body", [
    ("hi", "आपका KYC लंबित है। आज आपका बैंक खाता बंद हो जाएगा। तुरंत लिंक पर जाकर OTP भेजें।"),
    ("te", "మీ KYC పెండింగ్‌లో ఉంది. ఈరోజు మీ బ్యాంక్ ఖాతా బ్లాక్ అవుతుంది. వెంటనే OTP పంపండి."),
])
def test_quota_exhausted_gives_localized_template_with_limited_marker(wa, language, body):
    from services import llm_status

    llm_status.breaker.trip(600)
    post(wa, with_id(fixture("twilio_text.json"), 90, body))
    reply = wa.twilio.sent[0]["Body"]
    t = templates(language)
    assert t["limited"] in reply and len(reply) <= MAX_REPLY_CHARS
    assert any(t["label"][k] in reply for k in t["label"])
    assert checks(wa)[0]["language"] == language and checks(wa)[0]["llm_state"] == "quota_exhausted"


def test_hindi_image_without_hindi_ocr_data_says_so(wa, monkeypatch):
    from services import input_service, whatsapp_service

    async def read_image(image_b64, mime):
        return input_service.ImageRead("आपका KYC लंबित है, तुरंत OTP भेजें", "tesseract", "Image read without AI")

    monkeypatch.setattr(input_service, "read_image", read_image)
    monkeypatch.setattr(whatsapp_service, "ocr_languages", lambda: {"eng"})
    post(wa, fixture("twilio_image.json"))
    reply = wa.twilio.sent[0]["Body"]
    assert templates("hi")["ocr_missing"] in reply
    assert checks(wa)[0]["input_type"] == "image"


def test_image_with_no_readable_text(wa, monkeypatch):
    from services import input_service, whatsapp_service

    async def read_image(image_b64, mime):
        raise input_service.InputError("no text")

    monkeypatch.setattr(input_service, "read_image", read_image)
    monkeypatch.setattr(whatsapp_service, "ocr_languages", lambda: {"eng", "hin", "tel"})
    post(wa, fixture("twilio_image.json"))
    assert templates("en")["no_text"] in wa.twilio.sent[0]["Body"]


def test_too_long_text_is_refused_politely(wa, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_MAX_TEXT_CHARS", 50)
    post(wa, fixture("twilio_text.json"))
    assert templates("en")["too_large"] in wa.twilio.sent[0]["Body"]


# ------------------------------------------------------------------------------ abuse controls


def test_stop_and_start(wa):
    base = fixture("twilio_text.json")
    post(wa, with_id(base, 11, "STOP"))
    assert templates("en")["stopped"] in wa.twilio.sent[-1]["Body"]
    post(wa, with_id(base, 12))  # ignored while opted out
    assert len(wa.twilio.sent) == 1
    assert audit_events(wa, "whatsapp_ignored")
    post(wa, with_id(base, 13, "start"))
    assert templates("en")["started"] in wa.twilio.sent[-1]["Body"]
    post(wa, with_id(base, 14))
    assert len(wa.twilio.sent) == 3


def test_per_sender_rate_limit(wa, monkeypatch):
    from api.verify import RateLimiter
    from services import whatsapp_service

    monkeypatch.setattr(whatsapp_service, "sender_limiter", RateLimiter(2, noun="WhatsApp checks", window=3600))
    for n in range(3):
        post(wa, with_id(fixture("twilio_text.json"), 20 + n))
    assert len(wa.twilio.sent) == 2
    [limited] = audit_events(wa, "whatsapp_rate_limited")
    assert limited["actor"].startswith("whatsapp:") and SENDER_DIGITS not in limited["actor"]


def test_the_rate_limiter_supports_an_hour_window():
    from api.verify import RateLimiter

    now = [0.0]
    lim = RateLimiter(1, clock=lambda: now[0], noun="checks", window=3600)
    lim.check("a")
    now[0] = 1800
    assert lim.blocked("a") is not None and "per hour" in lim.blocked("a").detail
    now[0] = 3601
    assert lim.blocked("a") is None


# ------------------------------------------------------------------------------ privacy


def test_number_and_message_never_reach_the_database_or_the_logs(wa):
    params = fixture("twilio_text.json")
    logs: list[str] = []
    sink = logger.add(lambda m: logs.append(str(m)), level="DEBUG")
    try:
        post(wa, params)
        post(wa, with_id(params, 31, "Drinking hot water every 15 minutes kills the coronavirus, my uncle said"))
    finally:
        logger.remove(sink)
    assert len(wa.twilio.sent) == 2

    async def dump():
        from database import connection
        from database.models import Base

        out = []
        async with connection.session_factory()() as s:
            for table in Base.metadata.sorted_tables:
                for row in (await s.execute(text(f"SELECT * FROM {table.name}"))).all():
                    out.append(f"{table.name}: {tuple(row)}")
        return "\n".join(out)

    everything = wa.client.portal.call(dump) + "\n".join(logs)
    for secret in (SENDER_DIGITS, "Test Person", "sbi-kyc-update.example/verify", "Update KYC now", "my uncle said"):
        assert secret not in everything, secret
    sender_hash = hashlib.sha256(f"{settings.WHATSAPP_HASH_SALT}:{SENDER}".encode()).hexdigest()
    assert sender_hash in everything  # what is stored instead


def test_whatsapp_checks_show_in_the_inbox_filter(wa):
    post(wa, fixture("twilio_text.json"))
    resp = wa.client.get("/api/inbox", params={"source": "whatsapp"}, headers=OP)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1 and body["items"][0]["source"] == "whatsapp"


# ------------------------------------------------------------------------------ Meta Cloud API


def test_meta_webhook_checks_x_hub_signature_and_replies_as_dry_run(wa, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "meta")
    monkeypatch.setattr(settings, "META_APP_SECRET", "meta-app-secret-for-tests")
    body = (FIXTURES / "meta_text.json").read_bytes()
    good = "sha256=" + hmac.new(b"meta-app-secret-for-tests", body, hashlib.sha256).hexdigest()
    bad = wa.client.post("/api/whatsapp/webhook", content=body + b" ", headers={"X-Hub-Signature-256": good,
                                                                                "Content-Type": "application/json"})
    assert bad.status_code == 403
    ok = wa.client.post("/api/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": good,
                                                                        "Content-Type": "application/json"})
    assert ok.status_code == 200 and ok.json() == {"received": 1}
    assert wa.twilio.sent == []
    assert audit_events(wa, "whatsapp_reply")[0]["delivery"] == "dry_run"


# ------------------------------------------------------------------------------ send paths


def test_messaging_apis_are_called_only_from_the_whatsapp_provider():
    backend = settings.model_config["env_file"].parent
    hosts = ("api.twilio.com", "graph.facebook.com", "Messages.json", "messages.create")
    hits = []
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend).as_posix()
        if rel.startswith(("venv/", "tests/")) or "/__pycache__/" in rel:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        hits += [(rel, h) for h in hosts if h in content]
    assert {rel for rel, _ in hits} <= {"shield/providers/whatsapp.py"}, hits
    callers = [p.relative_to(backend).as_posix() for p in backend.rglob("*.py")
               if "send_text(" in p.read_text(encoding="utf-8", errors="ignore")
               and not p.relative_to(backend).as_posix().startswith(("venv/", "tests/"))]
    assert sorted(callers) == ["services/whatsapp_service.py", "shield/providers/whatsapp.py"]
