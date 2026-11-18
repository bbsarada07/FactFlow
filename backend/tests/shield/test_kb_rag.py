"""Tests for Knowledge Base RAG v1: ingestion, embeddings, retrieval, and latency."""
import asyncio
import time
import pytest
from sqlalchemy import func, select

from database.models import KBDocument
from shield.kb.embeddings import embed_batch, embed_text
from shield.kb.ingest import ingest_all
from shield.kb.retrieve import retrieve


def test_embeddings_empty_and_whitespace():
    """Embedding engine must handle empty and whitespace-only inputs without crashing."""
    empty_batch = embed_batch([])
    assert empty_batch.shape == (0, 384)

    mixed_batch = embed_batch(["valid query", "", "   ", "\t\n", "another text"])
    assert mixed_batch.shape == (5, 384)
    # empty/whitespace rows should be zero vectors
    assert float(mixed_batch[1].sum()) == 0.0
    assert float(mixed_batch[2].sum()) == 0.0
    assert float(mixed_batch[3].sum()) == 0.0
    assert float(mixed_batch[0].sum()) != 0.0
    assert float(mixed_batch[4].sum()) != 0.0

    single_empty = embed_text("")
    assert single_empty.shape == (384,)
    assert float(single_empty.sum()) == 0.0

    single_space = embed_text("   \n ")
    assert single_space.shape == (384,)
    assert float(single_space.sum()) == 0.0

    valid = embed_text("PM Surya Ghar")
    assert valid.shape == (384,)
    assert float(valid.sum()) != 0.0


def test_ingestion_idempotent_no_duplicates(with_db):
    """Running ingestion twice must not duplicate rows."""
    async def body(sf):
        async with sf() as session:
            stats1 = await ingest_all(session)
            total1 = stats1["total"]
            assert total1 >= 20  # at least 10 schemes + 10 scams + helpline
            
            count1 = await session.scalar(select(func.count(KBDocument.id)))
            assert count1 == total1

            # Run a second time
            stats2 = await ingest_all(session)
            count2 = await session.scalar(select(func.count(KBDocument.id)))
            assert count2 == count1, f"Expected {count1} rows, got {count2} after second ingestion"

    with_db(body)


def test_retrieval_returns_correct_document(with_db):
    """Retrieval returns the right document for an obvious query."""
    async def body(sf):
        async with sf() as session:
            await ingest_all(session)
            
            # Query for PM Surya Ghar
            hits = await retrieve("PM Surya Ghar free electricity rooftop solar subsidy", session)
            assert len(hits) >= 1
            top = hits[0]
            assert "Surya Ghar" in top.title
            assert top.score >= 0.60
            assert top.source_type == "scheme"
            assert top.source_url == "https://pmsuryaghar.gov.in/"
            assert top.verified is True
            assert len(top.excerpt) > 20

            # Query for Digital Arrest scam
            scam_hits = await retrieve("CBI police officer video call digital arrest parcel drugs money transfer", session)
            assert len(scam_hits) >= 1
            top_scam = scam_hits[0]
            assert "Digital Arrest" in top_scam.title
            assert top_scam.score >= 0.60
            assert top_scam.source_type == "scam_template"

    with_db(body)


def test_retrieval_unrelated_returns_empty(with_db):
    """Retrieval returns an empty list for completely unrelated queries."""
    async def body(sf):
        async with sf() as session:
            await ingest_all(session)
            
            hits = await retrieve("Cricket match score India vs Australia Melbourne test 2026", session)
            assert hits == [], f"Expected empty list for cricket query, got {hits}"

            recipe_hits = await retrieve("How to bake chocolate chip cookies with butter and vanilla", session)
            assert recipe_hits == [], f"Expected empty list for recipe query, got {recipe_hits}"

    with_db(body)


def test_retrieval_adversarial_near_misses_return_empty(with_db):
    """Adversarial queries with keyword overlap but unrelated semantic intent return empty."""
    near_misses = [
        "Electricity bill discount 50% cashback promo code tonight",
        "Solar panel technician salary and job openings in Bangalore",
        "Police traffic e-challan receipt payment status online",
        "Watch top 10 YouTube video reviews for new smartphones",
        "Digital camera photography tips for beginners",
    ]

    async def body(sf):
        async with sf() as session:
            await ingest_all(session)
            
            for query in near_misses:
                hits = await retrieve(query, session, threshold=0.60)
                assert hits == [], f"Adversarial query '{query}' should return empty, but returned {hits}"

    with_db(body)


def test_retrieval_latency_p95_under_200ms(with_db):
    """Latency test: p95 retrieval time must be under 200 ms against the full seed corpus."""
    queries = [
        "PM Surya Ghar rooftop solar electricity subsidy",
        "How to receive PM Kisan 2000 rupees installment",
        "Digital arrest Skype video call police threat",
        "Update electricity bill tonight connection cut off",
        "Part time YouTube like review job work from home",
        "Unrelated query about Bollywood movies",
        "Atal Pension Yojana monthly pension after 60",
        "Pradhan Mantri Awas Yojana urban housing subsidy",
        "UPI PIN collect request refund scam",
        "National Career Service employment portal registration",
    ]

    async def body(sf):
        async with sf() as session:
            await ingest_all(session)
            
            latencies_ms = []
            # Run 50 retrieval queries
            for i in range(50):
                q = queries[i % len(queries)]
                t0 = time.perf_counter()
                await retrieve(q, session)
                dt_ms = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(dt_ms)
            
            latencies_ms.sort()
            p50 = latencies_ms[int(len(latencies_ms) * 0.50)]
            p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
            
            print(f"\n[LATENCY REPORT] Corpus queries=50, p50={p50:.2f}ms, p95={p95:.2f}ms")
            assert p95 < 200.0, f"p95 latency {p95:.2f}ms exceeded 200ms requirement!"

    with_db(body)
