"""Sentence embeddings for retrieval (similar tickets, knowledge-base search, RAG grounding of the copilot).

* MiniLM (`sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions) — the spec's model, run on CPU, vectors
  L2-normalised so cosine similarity is a dot product (pgvector `<=>` cosine distance on an HNSW index).
* HashingEmbedder — a deterministic bag-of-words/bigram hash into the same 384 dimensions. Used when
  ENABLE_TRANSFORMERS=false (unit tests, machines without the model); keyword overlap still ranks sensibly.

Every stored vector records the embedder's `name`, and searches only compare vectors from the same model.
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import os
import re
from functools import lru_cache
from typing import Protocol

import numpy as np

from app.core.config import get_settings

log = logging.getLogger(__name__)

DIM = 384
MIN_WORDS = 4  # shorter dataset remarks ("Good", "Thank you") say nothing about a problem and are not embedded


class Embedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray: ...


class MiniLMEmbedder:
    dim = DIM

    def __init__(self, model_name: str) -> None:
        os.environ.setdefault("HF_HOME", str(get_settings().hf_home))
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self.model = SentenceTransformer(model_name, device="cpu")

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self.model.encode(
            [t or "." for t in texts], batch_size=128, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vectors, dtype=np.float32)


_TOKEN = re.compile(r"[a-z0-9₹]+")


class HashingEmbedder:
    """Deterministic stand-in: unigrams and bigrams hashed into 384 signed buckets, then L2-normalised."""

    name = "hashing-384-v1"
    dim = DIM

    def _one(self, text: str) -> np.ndarray:
        v = np.zeros(DIM, dtype=np.float32)
        tokens = [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in _TOKEN.findall((text or "").lower())]
        for gram in [*tokens, *(" ".join(p) for p in itertools.pairwise(tokens))]:
            h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "little")
            v[h % DIM] += 1.0 if (h >> 32) & 1 else -1.0
        norm = float(np.linalg.norm(v))
        return v / norm if norm else v

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._one(t) for t in texts]) if texts else np.zeros((0, DIM), dtype=np.float32)


_override: Embedder | None = None


def set_embedder(embedder: Embedder | None) -> None:
    """Tests inject an embedder; None restores the configured one."""
    global _override
    _override = embedder


@lru_cache
def _configured() -> Embedder:
    s = get_settings()
    if not s.enable_transformers:
        return HashingEmbedder()
    try:
        embedder = MiniLMEmbedder(s.embedding_model)
        log.info("loaded embedding model %s", s.embedding_model)
        return embedder
    except Exception:  # a missing model must not take the API down; searches fall back
        log.exception("could not load %s; falling back to the hashing embedder", s.embedding_model)
        return HashingEmbedder()


def get_embedder() -> Embedder:
    return _override or _configured()


def embed(texts: list[str]) -> np.ndarray:
    return get_embedder().encode(texts)


def ticket_text(subject: str | None, description: str) -> str:
    """What a ticket is searched by: the customer's words (the subject only when it adds something)."""
    description = (description or "").strip()
    subject = (subject or "").strip().rstrip("…")
    return description if not subject or description.startswith(subject) else f"{subject}. {description}"


def worth_embedding(description_source: str, description: str) -> bool:
    if description_source == "template":
        return False
    return description_source == "customer" or len((description or "").split()) >= MIN_WORDS
