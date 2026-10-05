"""Evaluate knowledge-base search and similar-ticket retrieval on fixed examples (ml/retrieval_examples.py).

Compares, on the seeded knowledge base in the development database:
  * meaning only   — MiniLM vectors, pgvector HNSW cosine search
  * keywords only  — PostgreSQL full text (ts_rank_cd, OR query)
  * hybrid         — both fused by Reciprocal Rank Fusion (what the app uses)
Metrics: recall@1, recall@3 and MRR. Also: for each ticket triple, is the paraphrase closer than the other problem.

Needs the database migrated and seeded (`.\\scripts\\dev.ps1 seed`) and the MiniLM model (downloaded on first use).
Output: ml/reports/retrieval_report.md

Usage:  python ml/eval_retrieval.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("HF_HOME", str(ROOT / "ml" / ".hf_cache"))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "ml"))

from retrieval_examples import KB_QUERIES, TICKET_TRIPLES  # noqa: E402

from app.ai.embeddings import embed, get_embedder  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal, dispose_engine  # noqa: E402
from app.repositories import retrieval as repo  # noqa: E402
from app.services import retrieval  # noqa: E402

REPORT = ROOT / "ml" / "reports" / "retrieval_report.md"


def metrics(ranked: list[list[str]], expected: list[str]) -> dict[str, float]:
    ranks = [r.index(e) + 1 if e in r else None for r, e in zip(ranked, expected, strict=True)]
    n = len(ranks)
    return {
        "recall@1": sum(1 for r in ranks if r == 1) / n,
        "recall@3": sum(1 for r in ranks if r is not None and r <= 3) / n,
        "mrr": sum(1 / r for r in ranks if r is not None) / n,
    }


APP = "hybrid (app settings)"


def hybrid(near: list, words: list, *, weight: float, min_similarity: float) -> list[int]:
    hits = retrieval.fuse(
        near,
        words,
        k=get_settings().rrf_k,
        min_similarity=min_similarity,
        keyword_only_top=retrieval.ARTICLE_KEYWORD_ONLY,
        keyword_weight=weight,
    )
    return [h.id for h in hits]


async def evaluate() -> tuple[dict[str, dict[str, float]], list[tuple[str, str, list[str]]]]:
    model = get_embedder().name
    s = get_settings()
    variants = {
        "meaning only": None,
        "keywords only": None,
        "hybrid, equal weights, threshold 0.35": (1.0, 0.35),
        "hybrid, keyword weight 0.3, threshold 0.35": (0.3, 0.35),
        APP: (s.keyword_weight, s.article_min_score),
    }
    results: dict[str, list[list[str]]] = {name: [] for name in variants}
    async with SessionLocal() as db:
        titles = {a.id: a.title for a in (await repo.articles_by_ids(db, list(range(1, 10_000)))).values()}
        if not titles:
            raise SystemExit("The knowledge base is empty — run .\\scripts\\dev.ps1 seed first.")
        for query, _ in KB_QUERIES:
            vector = embed([query])[0].tolist()
            near = await repo.nearest_articles(db, vector, model, category=None, limit=retrieval.CANDIDATES)
            words = await repo.keyword_articles(db, query, category=None, limit=retrieval.CANDIDATES)
            results["meaning only"].append([titles[i] for i, _ in near])
            results["keywords only"].append([titles[i] for i, _ in words])
            for name, params in variants.items():
                if params:
                    ids = hybrid(near, words, weight=params[0], min_similarity=params[1])
                    results[name].append([titles[i] for i in ids])
        await db.rollback()
    await dispose_engine()
    expected = [e for _, e in KB_QUERIES]
    misses = [(q, e, r[:3]) for (q, e), r in zip(KB_QUERIES, results[APP], strict=True) if e not in r[:3]]
    return {name: metrics(ranked, expected) for name, ranked in results.items()}, misses


def triples() -> list[tuple[str, float, float]]:
    out = []
    for a, b, c in TICKET_TRIPLES:
        va, vb, vc = embed([a, b, c])
        out.append((a, float(va @ vb), float(va @ vc)))
    return out


def main() -> None:
    scores, misses = asyncio.run(evaluate())
    pairs = triples()
    lines = [
        "# Retrieval evaluation",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `ml/eval_retrieval.py` · embedding model "
        f"`{get_embedder().name}` · {len(KB_QUERIES)} fixed knowledge-base queries, {len(TICKET_TRIPLES)} ticket "
        "triples ([ml/retrieval_examples.py](../retrieval_examples.py)).",
        "",
        "## Knowledge-base search",
        "",
        "| Method | Recall@1 | Recall@3 | MRR |",
        "|---|---|---|---|",
    ]
    for name, m in scores.items():
        lines.append(f"| {name} | {m['recall@1']:.2f} | {m['recall@3']:.2f} | {m['mrr']:.2f} |")
    s = get_settings()
    lines += [
        "",
        f"The app uses weighted Reciprocal Rank Fusion (k={s.rrf_k}): vectors weigh 1.0, keywords "
        f"{s.keyword_weight}, and vector matches below {s.article_min_score} cosine are dropped for articles. These "
        "values were chosen on the examples above (the rows show the alternatives), so treat them as tuned on a "
        "small set: with equal weights, generic words such as *order* or *days* pulled unrelated articles up, and "
        "a 0.35 cut-off dropped correct articles for short queries (correct articles score from 0.25).",
        "",
        "App-settings misses (expected article not in the top 3):",
        "",
    ]
    lines += [f"- “{q}” → expected *{e}*, got: {', '.join(got)}" for q, e, got in misses] or ["- none"]
    ok = sum(1 for _, pos, neg in pairs if pos > neg)
    lines += [
        "",
        "## Similar tickets — paraphrase vs. different problem",
        "",
        f"The paraphrase is closer than the different problem in **{ok} of {len(pairs)}** triples.",
        "",
        "| Complaint | Cosine to paraphrase | Cosine to other problem |",
        "|---|---|---|",
    ]
    lines += [f"| {a} | {pos:.2f} | {neg:.2f} |" for a, pos, neg in pairs]
    lines += [
        "",
        "Real-data spot checks are recorded in PROGRESS.md (step 7). Similar-ticket results in the app are filtered by "
        "the caller's visibility and drop vector matches below `SIMILAR_MIN_SCORE` (0.35) unless keywords also match.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
