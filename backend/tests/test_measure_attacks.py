"""scripts/measure_attacks.py counts honestly: an 'unavailable' run is not an attack that failed, a token budget
stops the run early and says so, and shield=on can run rules-only (no tokens). No model is called here."""
import importlib.util
import json

from config import BASE_DIR
from shield.sandbox_agent import SandboxRunResult

ATTACK = "04_white_on_white_injection.eml"


def load():
    spec = importlib.util.spec_from_file_location("_measure_attacks", BASE_DIR / "scripts" / "measure_attacks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_off(outcomes: list[str], tokens_per_call: int = 0):
    """A stand-in for run_vulnerable_assistant that returns the given outcomes in order and spends tokens."""
    from models import groq_client

    queue = list(outcomes)

    async def run(data, email_id=None):
        meter = groq_client._usage.get()
        if meter is not None:
            meter.prompt_tokens += tokens_per_call
        outcome = queue.pop(0)
        if outcome == "unavailable":
            return SandboxRunResult(shield="off", status="unavailable", detail="unavailable, nothing executed")
        executed = outcome == "executed"
        return SandboxRunResult(shield="off", status="complete", executed=executed,
                                outbox_entries=[{"kind": "forward"}] if executed else [])

    return run


def setup(env, monkeypatch, tmp_path, outcomes, tokens_per_call=0):
    m = load()
    monkeypatch.setattr(m, "LOCAL_DATA_DIR", tmp_path)

    async def reachable():
        return True

    monkeypatch.setattr(m, "check_llm_reachability", reachable)
    monkeypatch.setattr(m.sandbox_agent, "run_vulnerable_assistant", fake_off(outcomes, tokens_per_call))
    return m


def test_unavailable_runs_are_reported_and_excluded_from_the_rate(mail_env, monkeypatch, tmp_path):
    m = setup(mail_env, monkeypatch, tmp_path, ["executed", "unavailable", "not"])
    report = mail_env.client.portal.call(lambda: m.measure(runs=3, files=[ATTACK], shield_on="rules"))
    off = report["results"][ATTACK]["shield_off"]
    assert (off["runs"], off["completed"], off["unavailable"], off["executed"]) == (3, 2, 1, 1)
    assert off["executed_rate_pct"] == 50.0  # of the runs where the model answered
    on = report["results"][ATTACK]["shield_on"]
    assert on["executed"] == 0 and on["mode"] == "rules" and on["tokens"] == 0
    saved = json.loads(next(tmp_path.glob("attack_measurements_*.json")).read_text(encoding="utf-8"))
    assert saved["results"][ATTACK]["shield_off"]["unavailable"] == 1


def test_token_budget_stops_early_and_says_so(mail_env, monkeypatch, tmp_path):
    m = setup(mail_env, monkeypatch, tmp_path, ["not"] * 10, tokens_per_call=600)
    report = mail_env.client.portal.call(lambda: m.measure(runs=10, files=[ATTACK], shield_on="rules",
                                                           token_budget=1000))
    off = report["results"][ATTACK]["shield_off"]
    assert off["runs"] == 2  # 600 tokens, then 1200 >= 1000: stop
    assert report["stopped_early"] and "budget" in report["stopped_early"]
    assert report["tokens_used"]["total"] == 1200


def test_only_the_requested_files_are_measured(mail_env, monkeypatch, tmp_path):
    m = setup(mail_env, monkeypatch, tmp_path, ["not"])
    report = mail_env.client.portal.call(lambda: m.measure(runs=1, files=[ATTACK], shield_on="rules"))
    assert list(report["results"]) == [ATTACK]
