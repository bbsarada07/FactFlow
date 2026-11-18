"""Semantic retrieval over the FactFlow Knowledge Base (RAG v1).

Pure in-memory cosine similarity via NumPy over precomputed 384-dim vectors.
Zero LLM calls, zero network calls.
Strict threshold enforcement: if the top candidate is below threshold, returns an empty list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import KBDocument
from shield.kb.embeddings import embed_text

_SPACES = re.compile(r"\s+")


def make_excerpt(body: str, max_chars: int = 200) -> str:
    """Create a clean, one-line excerpt from document text."""
    if not body:
        return ""
    clean = _SPACES.sub(" ", body).strip()
    if len(clean) <= max_chars:
        return clean
    truncated = clean[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        truncated = truncated[:last_space]
    return truncated.rstrip(".,;:- ") + "..."


@dataclass(frozen=True)
class KBHit:
    """A verified knowledge base match returned by semantic retrieval."""

    id: str
    title: str
    score: float
    source_type: str
    source_url: str | None
    verified: bool
    excerpt: str
    body_text: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "score": round(self.score, 4),
            "source_type": self.source_type,
            "source_url": self.source_url,
            "verified": self.verified,
            "excerpt": self.excerpt,
        }


async def retrieve(
    query: str,
    session: AsyncSession,
    threshold: float | None = None,
    k: int = 5,
    source_type: str | None = None,
) -> list[KBHit]:
    """Retrieve top-k documents clearing the cosine similarity threshold.

    Returns an empty list if query is blank, or if the top match is below threshold.
    """
    if not query or not query.strip():
        return []

    thresh = settings.KB_SIMILARITY_THRESHOLD if threshold is None else threshold
    q_vec = embed_text(query)
    q_norm = np.linalg.norm(q_vec)
    if q_norm == 0:
        return []

    stmt = select(
        KBDocument.id,
        KBDocument.title,
        KBDocument.source_type,
        KBDocument.source_url,
        KBDocument.verified,
        KBDocument.body_text,
        KBDocument.embedding,
    )
    if source_type:
        stmt = stmt.where(KBDocument.source_type == source_type)

    rows = (await session.execute(stmt)).all()
    if not rows:
        return []

    valid_rows: list[tuple] = []
    embs: list[list[float]] = []
    for r in rows:
        emb = r[6]
        if emb and isinstance(emb, (list, tuple)) and len(emb) == 384:
            valid_rows.append(r)
            embs.append(emb)

    if not valid_rows:
        return []

    mat = np.array(embs, dtype=np.float32)
    # Both q_vec and doc embeddings are unit-normalized upon creation,
    # but re-normalizing guarantees strict cosine similarity [-1, 1].
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mat = mat / norms

    scores = np.dot(mat, q_vec / q_norm)

    top_idx = int(np.argmax(scores))
    top_score = float(scores[top_idx])

    # HARD CONSTRAINT: If top score is below threshold, return EMPTY list.
    if top_score < thresh:
        return []

    # Filter all matching candidates above threshold
    matching_indices = [i for i, s in enumerate(scores) if s >= thresh]
    matching_indices.sort(key=lambda idx: scores[idx], reverse=True)
    top_k_indices = matching_indices[:k]

    hits: list[KBHit] = []
    for idx in top_k_indices:
        r = valid_rows[idx]
        score = float(scores[idx])
        hits.append(
            KBHit(
                id=str(r[0]),
                title=str(r[1]),
                score=round(score, 4),
                source_type=str(r[2]),
                source_url=r[3],
                verified=bool(r[4]),
                excerpt=make_excerpt(str(r[5])),
                body_text=str(r[5]),
            )
        )
    return hits

