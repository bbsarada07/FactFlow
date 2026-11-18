"""Local CPU embedding engine for Knowledge Base RAG (v1).

Uses sentence-transformers with all-MiniLM-L6-v2 locally (CPU only, no API key, no network).
Vectors are 384-dimensional unit-normalized floats.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Load the embedding model once at startup from local cache (no network calls)."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer

            # local_files_only=True guarantees zero network requests in the retrieval path
            _model = SentenceTransformer(MODEL_NAME, local_files_only=True)
            logger.info("Loaded local embedding model %s (dim=%d)", MODEL_NAME, EMBEDDING_DIM)
        except Exception as exc:
            logger.error("Failed to load local embedding model %s: %s", MODEL_NAME, exc)
            raise
    return _model


def embed_batch(texts: list[str]) -> np.ndarray:
    """Embed a list of strings into normalized 384-dim vectors.

    Handles empty lists, empty strings, and whitespace-only strings without crashing.
    Empty/whitespace items receive zero-vector representations.
    """
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    model = get_model()
    n = len(texts)
    result = np.zeros((n, EMBEDDING_DIM), dtype=np.float32)

    valid_indices = []
    valid_texts = []
    for i, t in enumerate(texts):
        if t and t.strip():
            valid_indices.append(i)
            valid_texts.append(t.strip())

    if valid_texts:
        embs = model.encode(
            valid_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        for idx, emb in zip(valid_indices, embs):
            result[idx] = emb.astype(np.float32)

    return result


def embed_text(text: str | None) -> np.ndarray:
    """Embed a single text string into a normalized 384-dim vector.

    Returns a 384-dim zero vector if input is empty or whitespace-only.
    """
    if not text or not text.strip():
        return np.zeros(EMBEDDING_DIM, dtype=np.float32)
    return embed_batch([text])[0]

