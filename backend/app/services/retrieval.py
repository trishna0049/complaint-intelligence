"""Hybrid retrieval: meaning (MiniLM vectors on pgvector HNSW) + keywords (PostgreSQL full text), fused with
weighted Reciprocal Rank Fusion: score = 1 / (RRF_K + vector rank) + KEYWORD_WEIGHT / (RRF_K + keyword rank).

* Similar tickets — for the Ticket Details workspace and as grounding for the copilot. Results respect the
  caller's visibility (agents: own / team / created tickets). Vector matches below SIMILAR_MIN_SCORE are dropped
  unless the keywords also match, so "Good" never shows up as similar to "charged twice".
* Knowledge-base search — free text or "articles for this ticket"; articles of the ticket's category get a small
  boost, so a wrong triage category can't hide the right article.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import embed, get_embedder, ticket_text, worth_embedding
from app.core.config import get_settings
from app.models import KnowledgeArticle, Ticket, User
from app.repositories import retrieval as repo

log = logging.getLogger(__name__)

CANDIDATES = 50  # taken from each half before fusion
# Items found only by keywords are kept from the top of the keyword ranking: a whole complaint as the query
# matches many long texts on common words, a typed knowledge-base query is short and precise.
TICKET_KEYWORD_ONLY = 3
ARTICLE_KEYWORD_ONLY = 10

MatchedBy = Literal["meaning", "keywords", "both"]


@dataclass
class Hit:
    id: int
    score: float  # fused RRF score (only comparable within one result list)
    similarity: float | None = None  # cosine similarity of the vector match, if any
    matched_by: MatchedBy = "meaning"
    sources: set[str] = field(default_factory=set)


def fuse(
    vector: list[tuple[int, float]],
    keyword: list[tuple[int, float]],
    *,
    k: int,
    min_similarity: float,
    keyword_only_top: int,
    keyword_weight: float = 1.0,
    boost: set[int] | None = None,
) -> list[Hit]:
    """Reciprocal Rank Fusion of the two rankings (best first). Pure — unit-tested on its own.

    A keyword match always adds to an item the vector search also found; an item found ONLY by keywords is kept
    when it is among the top `keyword_only_top` keyword matches (exact terms such as an order ID or "OTP")."""
    hits: dict[int, Hit] = {}
    for rank, (item, sim) in enumerate(vector, start=1):
        if sim < min_similarity:
            continue
        hits[item] = Hit(item, 1 / (k + rank), similarity=sim, sources={"meaning"})
    for rank, (item, _) in enumerate(keyword, start=1):
        if item not in hits and rank > keyword_only_top:
            continue
        hit = hits.setdefault(item, Hit(item, 0.0, sources=set()))
        hit.score += keyword_weight / (k + rank)
        hit.sources.add("keywords")
    nudge = 1 / (k + 1) - 1 / (k + 3)  # worth about two places at the top of a ranking: a nudge, not an override
    for item in boost or set():
        if item in hits:
            hits[item].score += nudge
    for hit in hits.values():
        hit.matched_by = "both" if len(hit.sources) == 2 else next(iter(hit.sources))  # type: ignore[assignment]
    return sorted(hits.values(), key=lambda h: (-h.score, -(h.similarity or 0), h.id))


async def _vector_for(texts: list[str]) -> list[float]:
    return (await asyncio.to_thread(embed, texts))[0].tolist()


# ------------------------------------------------------------------------------------------------ tickets
async def embed_ticket(db: AsyncSession, t: Ticket) -> bool:
    """Store the ticket's embedding (in the caller's transaction). A failure is logged, never fatal — the
    backfill script (scripts.embed_tickets) fills any gaps."""
    if not worth_embedding(t.description_source, t.description):
        return False
    try:
        text = ticket_text(t.subject if t.source == "new" else None, t.description)
        await repo.upsert_ticket_embedding(db, t.id, await _vector_for([text]), get_embedder().name)
        return True
    except Exception:
        log.exception("could not embed ticket %s", t.id)
        return False


@dataclass
class SimilarTicket:
    ticket: Ticket
    hit: Hit


async def similar_tickets(db: AsyncSession, user: User, t: Ticket, *, limit: int = 5) -> list[SimilarTicket]:
    from app.services.tickets import visibility_clause  # local: tickets imports this module

    s = get_settings()
    model = get_embedder().name
    text = ticket_text(t.subject if t.source == "new" else None, t.description)
    vector = await repo.ticket_vector(db, t.id, model) or await _vector_for([text])
    clause = visibility_clause(user)
    near = await repo.nearest_tickets(db, vector, model, visible=clause, exclude_id=t.id, limit=CANDIDATES)
    words = await repo.keyword_tickets(db, text, visible=clause, exclude_id=t.id, limit=CANDIDATES)
    hits = fuse(
        near,
        words,
        k=s.rrf_k,
        min_similarity=s.similar_min_score,
        keyword_only_top=TICKET_KEYWORD_ONLY,
        keyword_weight=s.keyword_weight,
    )[:limit]
    found = await repo.tickets_by_ids(db, [h.id for h in hits])
    return [SimilarTicket(found[h.id], h) for h in hits if h.id in found]


# ------------------------------------------------------------------------------------------------ articles
def article_text(a: KnowledgeArticle) -> str:
    return f"{a.title}\n{a.body}"


async def embed_article(a: KnowledgeArticle) -> None:
    vector = await _vector_for([article_text(a)])
    a.embedding, a.embedding_model = vector, get_embedder().name


@dataclass
class ArticleHit:
    article: KnowledgeArticle
    hit: Hit


async def search_articles(
    db: AsyncSession,
    query: str,
    *,
    category: str | None = None,
    boost_category: str | None = None,
    limit: int = 5,
) -> list[ArticleHit]:
    """`category` filters (Knowledge Base page); `boost_category` only nudges (articles for a ticket)."""
    s = get_settings()
    if not query.strip():
        return []
    vector = await _vector_for([query])
    near = await repo.nearest_articles(db, vector, get_embedder().name, category=category, limit=CANDIDATES)
    words = await repo.keyword_articles(db, query, category=category, limit=CANDIDATES)
    boost: set[int] = set()
    if boost_category:
        candidates = await repo.articles_by_ids(db, [i for i, _ in near] + [i for i, _ in words])
        boost = {i for i, a in candidates.items() if a.category == boost_category}
    hits = fuse(
        near,
        words,
        k=s.rrf_k,
        min_similarity=s.article_min_score,
        keyword_only_top=ARTICLE_KEYWORD_ONLY,
        keyword_weight=s.keyword_weight,
        boost=boost,
    )[:limit]
    found = await repo.articles_by_ids(db, [h.id for h in hits])
    return [ArticleHit(found[h.id], h) for h in hits if h.id in found]


async def articles_for_ticket(db: AsyncSession, t: Ticket, *, limit: int = 3) -> list[ArticleHit]:
    text = ticket_text(t.subject if t.source == "new" else None, t.description)
    return await search_articles(db, text, boost_category=t.category, limit=limit)
