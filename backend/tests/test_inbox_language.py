"""explanation.user_language must name the language the explanation text is actually in. Rules-only and
quota-exhausted results carry the English rules summary, so they must say "en" even when Hindi was requested."""
from services import llm_status

HINDI_SCAM = "आपका KYC लंबित है। आज आपका बैंक खाता बंद हो जाएगा। तुरंत OTP भेजें।"


def analyze(env, mode: str, language: str = "hi") -> dict:
    resp = env.client.post("/api/inbox/analyze", json={"raw": HINDI_SCAM, "language": language, "mode": mode,
                                                        "wait": True, "force": True})
    assert resp.status_code == 200, resp.text
    return resp.json()["verdict"]


def test_rules_only_explanation_is_labelled_english(mail_env):
    v = analyze(mail_env, "rules")
    assert v["llm_status"]["state"] == "not_used"
    assert v["explanation"]["user_language"] == "en"


def test_quota_exhausted_explanation_is_labelled_english(mail_env):
    llm_status.breaker.trip(600)
    v = analyze(mail_env, "full")
    assert v["llm_status"]["state"] == "quota_exhausted"
    assert v["explanation"]["user_language"] == "en"


def test_explainer_output_keeps_the_requested_language(mail_env):
    v = analyze(mail_env, "full")
    assert v["llm_status"]["state"] == "ok"
    assert v["explanation"]["text"] == "Stand-in explanation."
    assert v["explanation"]["user_language"] == "hi"
