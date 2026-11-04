"""Tests for Step 3: Shield Scam Template Semantic Retrieval (RAG v1)."""
from database import connection
from shield.kb.ingest import ingest_all
from shield.scan import scan_raw
from shield.scam_patterns import scan_with_template


def test_scam_template_matching_message(with_db, monkeypatch):
    """A message matching a seeded scam template shows the extra template evidence."""
    async def body(sf):
        monkeypatch.setattr(connection, "SessionLocal", sf)
        async with sf() as session:
            await ingest_all(session)

        message = (
            "Dear consumer, your electricity power will be disconnected tonight at 9:30 PM "
            "because your previous month bill was not updated. Please call our power officer "
            "immediately at 9876543210 to avoid disconnection."
        )

        verdict = scan_raw(message)
        scam = verdict.components.scam

        # Existing rule-based detectors still fire (SC-07 is electricity disconnection)
        assert len(scam.detectors) >= 1
        rule_ids = {d.id for d in scam.detectors}
        assert "SC-07" in rule_ids

        # Additive template hit is present with template_id, template_name, score, excerpt
        assert scam.template_hit is not None
        assert scam.template_hit.template_id == "scam_electricity_disconnection"
        assert "Electricity" in scam.template_hit.template_name
        assert scam.template_hit.score >= 0.60
        assert len(scam.template_hit.excerpt) > 20
        assert "Matching scam template" in verdict.explanation.en

    with_db(body)


def test_scam_template_benign_message(with_db, monkeypatch):
    """A benign message returns no scam template hit and zero scam detectors."""
    async def body(sf):
        monkeypatch.setattr(connection, "SessionLocal", sf)
        async with sf() as session:
            await ingest_all(session)

        benign = (
            "Hi team, just sharing the slide deck from today's sprint demo. "
            "Please review the notes and leave comments before our sync tomorrow morning."
        )

        verdict = scan_raw(benign)
        scam = verdict.components.scam

        assert len(scam.detectors) == 0
        assert scam.template_hit is None
        assert scam.score == 0
        assert "Matching scam template" not in verdict.explanation.en

    with_db(body)


def test_scam_patterns_scan_with_template_direct(with_db, monkeypatch):
    """Direct helper in scam_patterns returns both rule hits and the template hit."""
    async def body(sf):
        monkeypatch.setattr(connection, "SessionLocal", sf)
        async with sf() as session:
            await ingest_all(session)

        digital_arrest_text = (
            "This is Deputy Commissioner from Cyber Crime CBI. You are under digital arrest on this Skype video call "
            "regarding an illegal parcel with drugs. Transfer verification money to RBI account immediately."
        )

        hits, template_hit = scan_with_template(digital_arrest_text)
        assert len(hits) >= 1
        rule_ids = {h.id for h in hits}
        assert "SC-01" in rule_ids

        assert template_hit is not None
        assert template_hit.template_id == "scam_digital_arrest"
        assert "Digital Arrest" in template_hit.template_name
        assert template_hit.score >= 0.60

    with_db(body)


def test_scam_template_is_additive_never_changes_severity():
    """Template hit is additive evidence only and does not inflate rule-based detector scores."""
    from shield.schemas import ScamComponent, ScamHit, ScamTemplateEvidence
    from shield.scoring import severity_score

    detector = ScamHit(id="SC-TEST", name="Test Detector", matched_evidence=["evidence"], severity="high")
    tpl = ScamTemplateEvidence(
        template_id="scam-test",
        template_name="Test Scam Template",
        score=0.92,
        excerpt="Known test scam excerpt",
    )

    comp_without_tpl = ScamComponent(
        score=severity_score([detector.severity]),
        detectors=[detector],
    )

    comp_with_tpl = ScamComponent(
        score=severity_score([detector.severity]),
        detectors=[detector],
        template_hit=tpl,
    )

    assert comp_with_tpl.score == comp_without_tpl.score
    assert len(comp_with_tpl.detectors) == len(comp_without_tpl.detectors)
    assert comp_with_tpl.template_hit == tpl
