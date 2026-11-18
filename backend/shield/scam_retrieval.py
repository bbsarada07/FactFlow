"""Scam template semantic retrieval for Shield (RAG v1).

Additive signal: queries kb_documents for source_type='scam_template' using
pure in-memory NumPy cosine similarity over local embeddings.
Never replaces rule-based detectors; provides additional evidence to the verdict.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import TYPE_CHECKING

from config import settings
from shield.kb.retrieve import retrieve
from shield.schemas import ScamTemplateEvidence

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def a_retrieve_scam_template(
    text: str,
    session: AsyncSession | None = None,
    session_factory=None,
    threshold: float | None = None,
) -> ScamTemplateEvidence | None:
    """Retrieve the closest matching scam template above the threshold."""
    if not text or not text.strip():
        return None

    thresh = settings.KB_SIMILARITY_THRESHOLD if threshold is None else threshold

    try:
        if session is not None:
            hits = await retrieve(text, session, threshold=thresh, k=1, source_type="scam_template")
        elif session_factory is not None:
            async with session_factory() as sess:
                hits = await retrieve(text, sess, threshold=thresh, k=1, source_type="scam_template")
        else:
            from database import connection
            if connection.SessionLocal is None:
                await connection.init_db()
            async with connection.session_factory()() as sess:
                hits = await retrieve(text, sess, threshold=thresh, k=1, source_type="scam_template")
    except Exception:
        # DB unavailable or retrieval failure; fail soft
        return None

    if not hits:
        return None

    top = hits[0]
    return ScamTemplateEvidence(
        template_id=top.id,
        template_name=top.title,
        score=round(top.score, 4),
        excerpt=top.excerpt,
    )


def retrieve_scam_template(
    text: str,
    session: AsyncSession | None = None,
    session_factory=None,
    threshold: float | None = None,
) -> ScamTemplateEvidence | None:
    """Synchronous wrapper for scan pipeline contexts."""
    if not text or not text.strip():
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    lambda: asyncio.run(
                        a_retrieve_scam_template(
                            text, session=session, session_factory=session_factory, threshold=threshold
                        )
                    )
                ).result()
        else:
            return asyncio.run(
                a_retrieve_scam_template(
                    text, session=session, session_factory=session_factory, threshold=threshold
                )
            )
    except Exception:
        return None
