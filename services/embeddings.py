"""Mistral embeddings wrapper for semantic menu search.

Thin, lazy, and graceful: if the API key is missing or a call fails, the
helpers return None and callers fall back to keyword search. mistral-embed
produces 1024-dim vectors (config.EMBEDDING_DIM).
"""

from __future__ import annotations

from loguru import logger

from config import MISTRAL_API_KEY, MISTRAL_EMBED_MODEL

try:  # SDK is a namespace package; the client lives under mistralai.client
    from mistralai.client import Mistral
except Exception:  # pragma: no cover - import shape guard
    Mistral = None  # type: ignore

_client = None


def _get_client():
    global _client
    if _client is None and Mistral is not None and MISTRAL_API_KEY:
        _client = Mistral(api_key=MISTRAL_API_KEY)
    return _client


def embeddings_enabled() -> bool:
    """True when embeddings can be produced (key + SDK present)."""
    return _get_client() is not None


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embed a batch of texts. Returns None (not partial) on any failure."""
    client = _get_client()
    if client is None or not texts:
        return None
    try:
        resp = client.embeddings.create(model=MISTRAL_EMBED_MODEL, inputs=texts)
        return [list(d.embedding) for d in resp.data]
    except Exception as e:  # network/quota/model errors degrade to keyword search
        logger.warning(f"Embedding request failed, falling back to keyword search: {e}")
        return None


def embed_text(text: str) -> list[float] | None:
    out = embed_texts([text])
    return out[0] if out else None
