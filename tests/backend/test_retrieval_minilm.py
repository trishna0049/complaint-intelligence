"""MiniLM on the fixed retrieval examples (ml/retrieval_examples.py). Runs only where the model is already cached
locally (ml/.hf_cache — `.\\scripts\\dev.ps1 seed` or `train` downloads it); CI without the cache skips it.
Meaning-only thresholds sit a little below the measured values in ml/reports/retrieval_report.md."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "ml" / ".hf_cache" / "hub" / "models--sentence-transformers--all-MiniLM-L6-v2"
pytestmark = pytest.mark.skipif(not CACHE.is_dir(), reason="MiniLM not cached locally")

sys.path.insert(0, str(ROOT / "ml"))
from retrieval_examples import KB_QUERIES, TICKET_TRIPLES  # noqa: E402

from scripts.knowledge_seed import ARTICLES  # noqa: E402


@pytest.fixture(scope="module")
def minilm():
    os.environ["HF_HOME"] = str(ROOT / "ml" / ".hf_cache")
    os.environ["HF_HUB_OFFLINE"] = "1"  # never download in tests
    from app.ai.embeddings import MiniLMEmbedder

    return MiniLMEmbedder("sentence-transformers/all-MiniLM-L6-v2")


def test_articles_are_found_by_meaning(minilm):
    titles = [a["title"] for a in ARTICLES]
    docs = minilm.encode([f"{a['title']}\n{a['body']}" for a in ARTICLES])
    queries = minilm.encode([q for q, _ in KB_QUERIES])
    ranks = []
    for (_, expected), q in zip(KB_QUERIES, queries, strict=True):
        order = [titles[i] for i in np.argsort(-(docs @ q))]
        ranks.append(order.index(expected) + 1)
    recall3 = sum(r <= 3 for r in ranks) / len(ranks)
    mrr = sum(1 / r for r in ranks) / len(ranks)
    assert recall3 >= 0.9 and mrr >= 0.85, (recall3, mrr, ranks)
    assert dim_ok(docs)


def dim_ok(vectors: np.ndarray) -> bool:
    return vectors.shape[1] == 384 and np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4)


def test_paraphrases_are_closer_than_other_problems(minilm):
    for a, b, c in TICKET_TRIPLES:
        va, vb, vc = minilm.encode([a, b, c])
        assert va @ vb > va @ vc, (a, float(va @ vb), float(va @ vc))


def test_charged_twice_finds_the_duplicate_payment_article(minilm):
    """The spec's example complaint: the payment article must come first."""
    titles = [a["title"] for a in ARTICLES]
    docs = minilm.encode([f"{a['title']}\n{a['body']}" for a in ARTICLES])
    q = minilm.encode(["I was charged twice for my order of ₹12,500 and have already contacted support three times."])[
        0
    ]
    assert titles[int(np.argmax(docs @ q))] == "Duplicate or double payment for one order"
