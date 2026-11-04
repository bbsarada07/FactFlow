"""Tests for Step 2 & 5: Source Tracer, Explainer, and API exposure (RAG v1)."""
import asyncio
from unittest.mock import AsyncMock

from agents.context import PipelineContext
from agents import explainer, source_tracer
from config import settings
from database import connection
from database.models import Claim, Source
from models.groq_client import LLMResult
from shield.kb.ingest import ingest_all


def setup_kb(db_url, monkeypatch):
    """Initialise test database and ingest the seed knowledge base."""
    monkeypatch.setattr(settings, "ASYNC_DATABASE_URL", db_url)
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)


def test_source_tracer_retrieves_internal_kb_scheme(db_url, monkeypatch):
    """Claim matching a seeded scheme retrieves internal KB doc, labels it, and Explainer cites it."""
    setup_kb(db_url, monkeypatch)

    async def body():
        await connection.init_db()
        async with connection.session_factory()() as session:
            await ingest_all(session)

        # Mock external providers to return nothing so only internal KB fires
        monkeypatch.setattr("agents.source_tracer.search_factchecks", AsyncMock(return_value=[]))
        monkeypatch.setattr("agents.source_tracer.search_newsapi", AsyncMock(return_value=[]))
        monkeypatch.setattr("agents.source_tracer.search_gdelt", AsyncMock(return_value=[]))
        monkeypatch.setattr("agents.source_tracer.search_duckduckgo", AsyncMock(return_value=[]))

        # Mock Nano for Source Tracer
        async def fake_tracer_nano(*args, **kwargs):
            return LLMResult(
                data={
                    "assessments": [{"i": 1, "relevance": 0.95, "stance": "SUPPORTS"}],
                    "verdict": "TRUE",
                    "confidence": 0.95,
                    "summary": "PM Surya Ghar provides up to 300 units of free electricity per month for rooftop solar installations [1].",
                    "reasoning": ["The official scheme portal details 300 units free solar electricity [1]."],
                    "contradictions_found": [],
                    "missing_context": [],
                    "evidence_gaps": [],
                    "fact": "The official PM Surya Ghar scheme provides rooftop solar subsidies [1].",
                    "key_source": "PM Surya Ghar Muft Bijli Yojana (Internal KB: scheme)",
                },
                model="fake-nano",
                ms=10,
                tokens=100,
            )

        monkeypatch.setattr("agents.source_tracer.call_nano", fake_tracer_nano)

        claim_text = "Government launched PM Surya Ghar Muft Bijli Yojana offering 300 units free electricity rooftop solar subsidy"
        ctx = PipelineContext(
            request_id="test-rag-1",
            raw_text=claim_text,
            claim=claim_text,
            today="2026-11-04",
        )

        out = await source_tracer.run(ctx)

        assert len(ctx.evidence) == 1
        ev = ctx.evidence[0]
        assert ev["origin"] == "internal"
        assert "PM Surya Ghar" in ev["name"]
        assert ev["ref"] == "S1"
        assert "pmsuryaghar.gov.in" in ev["url"]
        assert ev["tier"] == 1  # gov.in domain gets Tier 1
        assert "1 internal, 0 web" in out.preview
        assert ctx.verdict == "TRUE"

        # Now test Explainer with internal citation
        async def fake_explainer_nano(*args, **kwargs):
            return LLMResult(
                data={
                    "simple_summary": "According to the official scheme page [S1], households receive up to 300 units of free solar electricity.",
                    "local_summary": "According to the official scheme page [S1], households receive up to 300 units of free solar electricity.",
                    "myth": "PM Surya Ghar provides 300 units free solar electricity",
                    "fact": "According to verified records [S1], the government subsidises rooftop solar up to 300 units monthly.",
                    "whatsapp_reply": "This is verified. PM Surya Ghar offers rooftop solar subsidies. — Checked with FactFlow",
                    "correction_en": "PM Surya Ghar verified by official scheme records.",
                    "correction_hi": "पीएम सूर्य घर योजना आधिकारिक रिकॉर्ड से पुष्ट है।",
                    "correction_te": "పీఎం సూర్య ఘర్ పథకం ధృవీకరించబడింది.",
                },
                model="fake-nano",
                ms=12,
                tokens=120,
            )

        monkeypatch.setattr("agents.explainer.call_nano", fake_explainer_nano)

        await explainer.run(ctx)
        assert "[S1]" in ctx.summary
        assert "official scheme page" in ctx.summary
        assert "[S1]" in ctx.fact
        assert "According to verified records" in ctx.fact

    asyncio.run(body())


def test_source_tracer_regression_no_kb_match(db_url, monkeypatch):
    """Claim with no KB match returns UNVERIFIED with zero evidence (regression test)."""
    setup_kb(db_url, monkeypatch)

    async def body():
        await connection.init_db()
        async with connection.session_factory()() as session:
            await ingest_all(session)

        monkeypatch.setattr("agents.source_tracer.search_factchecks", AsyncMock(return_value=[]))
        monkeypatch.setattr("agents.source_tracer.search_newsapi", AsyncMock(return_value=[]))
        monkeypatch.setattr("agents.source_tracer.search_gdelt", AsyncMock(return_value=[]))
        monkeypatch.setattr("agents.source_tracer.search_duckduckgo", AsyncMock(return_value=[]))

        claim_text = "Alien spacecraft photographed landing in Central Park yesterday afternoon"
        ctx = PipelineContext(
            request_id="test-rag-2",
            raw_text=claim_text,
            claim=claim_text,
            today="2026-11-04",
        )

        out = await source_tracer.run(ctx)
        assert ctx.verdict == "UNVERIFIED"
        assert len(ctx.evidence) == 0
        assert "0 relevant" in out.preview

        # Explainer should fall back cleanly
        await explainer.run(ctx)
        assert "No sources found yet" in ctx.summary
        assert ctx.verdict == "UNVERIFIED"

    asyncio.run(body())


def test_internal_hit_not_automatically_trusted(db_url, monkeypatch):
    """Internal KB hits are subjected to relevance scoring and dropped if not relevant."""
    setup_kb(db_url, monkeypatch)

    async def body():
        await connection.init_db()
        async with connection.session_factory()() as session:
            await ingest_all(session)

        monkeypatch.setattr("agents.source_tracer.search_factchecks", AsyncMock(return_value=[]))
        monkeypatch.setattr("agents.source_tracer.search_newsapi", AsyncMock(return_value=[]))
        monkeypatch.setattr("agents.source_tracer.search_gdelt", AsyncMock(return_value=[]))
        monkeypatch.setattr("agents.source_tracer.search_duckduckgo", AsyncMock(return_value=[]))

        # LLM assesses the internal hit as irrelevant (< 0.35)
        async def fake_tracer_nano(*args, **kwargs):
            return LLMResult(
                data={
                    "assessments": [{"i": 1, "relevance": 0.15, "stance": "NEUTRAL"}],
                    "verdict": "UNVERIFIED",
                    "confidence": 0.0,
                    "summary": "",
                    "reasoning": [],
                    "contradictions_found": [],
                    "missing_context": [],
                    "evidence_gaps": ["insufficient evidence"],
                    "fact": "",
                    "key_source": "",
                },
                model="fake-nano",
                ms=10,
                tokens=100,
            )

        monkeypatch.setattr("agents.source_tracer.call_nano", fake_tracer_nano)

        claim_text = "PM Surya Ghar rooftop solar scheme gives free electric cars to all citizens"
        ctx = PipelineContext(
            request_id="test-rag-3",
            raw_text=claim_text,
            claim=claim_text,
            today="2026-11-04",
        )

        out = await source_tracer.run(ctx)
        # The low relevance candidate must be dropped, leaving 0 relevant evidence
        assert len(ctx.evidence) == 0
        assert ctx.verdict == "UNVERIFIED"

    asyncio.run(body())


def test_claim_to_public_and_to_result_internal_citations():
    """Verify internal citations field in public and result API schemas."""
    claim = Claim(
        id="claim-test-1",
        raw_input="Solar scheme test",
        claim_text="Solar scheme test",
        verdict="TRUE",
        confidence=0.9,
    )
    s1 = Source(
        ref="S1",
        name="PM Surya Ghar (Internal KB: scheme)",
        url="https://pmsuryaghar.gov.in",
        title="PM Surya Ghar Scheme",
        snippet="Official scheme rooftop solar 300 units",
        origin="internal",
        tier=1,
        credibility=0.95,
        stance="SUPPORTS",
    )
    s2 = Source(
        ref="S2",
        name="PIB News",
        url="https://pib.gov.in/news",
        title="PIB News Release",
        snippet="Government cabinet approves scheme",
        origin="newsapi",
        tier=1,
        credibility=0.95,
        stance="SUPPORTS",
    )
    claim.sources = [s1, s2]

    public = claim.to_public()
    assert "internal_citations" in public
    assert len(public["internal_citations"]) == 1
    cit = public["internal_citations"][0]
    assert cit["ref"] == "S1"
    assert cit["title"] == "PM Surya Ghar Scheme"
    assert cit["source_url"] == "https://pmsuryaghar.gov.in"
    assert cit["stance"] == "SUPPORTS"

    res = claim.to_result()
    assert "internal_citations" in res
    assert len(res["internal_citations"]) == 1
    assert res["internal_citations"][0]["ref"] == "S1"

    # Empty case
    claim_empty = Claim(id="c2", raw_input="none")
    claim_empty.sources = [s2]
    assert claim_empty.to_public()["internal_citations"] == []
    assert claim_empty.to_result()["internal_citations"] == []
