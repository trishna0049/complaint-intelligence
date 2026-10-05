"""Retrieval queries: nearest neighbours on the pgvector HNSW indexes and full-text matches (the two halves of the
hybrid search fused in services.retrieval). No business rules — visibility arrives as a ready-made condition."""

from __future__ import annotations

import re
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeArticle, Ticket, TicketEmbedding

_WORD = re.compile(r"[a-z0-9]{3,}")
MAX_TERMS = 32
# ts_rank_cd normalisation 1: divide by 1 + log(document length), so long texts don't win just by containing many
# of the (OR-ed) query words.
LENGTH_NORMALISED = 1


def or_query(raw: str) -> str | None:
    """A tsquery that matches ANY of the words (ranked by how many and how rare): `w1 | w2 | ...`. Words are
    reduced to [a-z0-9] so user input can never break the tsquery syntax."""
    words = list(dict.fromkeys(_WORD.findall((raw or "").lower())))[:MAX_TERMS]
    return " | ".join(words) or None


async def _iterative_scan(db: AsyncSession) -> None:
    # pgvector >= 0.8: keep scanning the HNSW graph until enough rows pass the WHERE filters (visibility, model).
    await db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    await db.execute(text("SET LOCAL hnsw.ef_search = 100"))


# ------------------------------------------------------------------------------------------------ tickets
async def ticket_vector(db: AsyncSession, ticket_id: int, model: str) -> list[float] | None:
    vec = await db.scalar(
        select(TicketEmbedding.embedding).where(
            TicketEmbedding.ticket_id == ticket_id, TicketEmbedding.model_name == model
        )
    )
    return None if vec is None else list(vec)


async def upsert_ticket_embedding(db: AsyncSession, ticket_id: int, vector: Sequence[float], model: str) -> None:
    stmt = insert(TicketEmbedding).values(ticket_id=ticket_id, embedding=list(vector), model_name=model)
    await db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_ticket_embeddings_ticket_model", set_={"embedding": stmt.excluded.embedding}
        )
    )


async def nearest_tickets(
    db: AsyncSession,
    vector: Sequence[float],
    model: str,
    *,
    visible: ColumnElement[bool],
    exclude_id: int | None,
    limit: int,
) -> list[tuple[int, float]]:
    await _iterative_scan(db)
    distance = TicketEmbedding.embedding.cosine_distance(list(vector))
    stmt = (
        select(TicketEmbedding.ticket_id, (1 - distance).label("similarity"))
        .join(Ticket, Ticket.id == TicketEmbedding.ticket_id)
        .where(TicketEmbedding.model_name == model, visible)
        .order_by(distance)
        .limit(limit)
    )
    if exclude_id is not None:
        stmt = stmt.where(Ticket.id != exclude_id)
    rows = (await db.execute(stmt)).all()
    return sorted(((tid, float(sim)) for tid, sim in rows), key=lambda r: -r[1])


async def keyword_tickets(
    db: AsyncSession, raw: str, *, visible: ColumnElement[bool], exclude_id: int | None, limit: int
) -> list[tuple[int, float]]:
    query = or_query(raw)
    if not query:
        return []
    tsq = func.to_tsquery("english", query)
    rank = func.ts_rank_cd(Ticket.description_tsv, tsq, LENGTH_NORMALISED)
    stmt = (
        select(Ticket.id, rank.label("rank"))
        .where(Ticket.description_tsv.op("@@")(tsq), Ticket.description_source != "template", visible)
        .order_by(rank.desc(), Ticket.id.desc())
        .limit(limit)
    )
    if exclude_id is not None:
        stmt = stmt.where(Ticket.id != exclude_id)
    return [(tid, float(r)) for tid, r in (await db.execute(stmt)).all()]


async def tickets_by_ids(db: AsyncSession, ids: list[int]) -> dict[int, Ticket]:
    if not ids:
        return {}
    rows = await db.scalars(select(Ticket).where(Ticket.id.in_(ids)))
    return {t.id: t for t in rows.unique().all()}


# ------------------------------------------------------------------------------------------------ articles
async def nearest_articles(
    db: AsyncSession, vector: Sequence[float], model: str, *, category: str | None, limit: int
) -> list[tuple[int, float]]:
    await _iterative_scan(db)
    distance = KnowledgeArticle.embedding.cosine_distance(list(vector))
    stmt = (
        select(KnowledgeArticle.id, (1 - distance).label("similarity"))
        .where(KnowledgeArticle.embedding_model == model)
        .order_by(distance)
        .limit(limit)
    )
    if category:
        stmt = stmt.where(KnowledgeArticle.category == category)
    rows = (await db.execute(stmt)).all()
    return sorted(((aid, float(sim)) for aid, sim in rows), key=lambda r: -r[1])


async def keyword_articles(db: AsyncSession, raw: str, *, category: str | None, limit: int) -> list[tuple[int, float]]:
    query = or_query(raw)
    if not query:
        return []
    tsq = func.to_tsquery("english", query)
    rank = func.ts_rank_cd(KnowledgeArticle.search_vector, tsq, LENGTH_NORMALISED)
    stmt = (
        select(KnowledgeArticle.id, rank.label("rank"))
        .where(KnowledgeArticle.search_vector.op("@@")(tsq))
        .order_by(rank.desc(), KnowledgeArticle.id)
        .limit(limit)
    )
    if category:
        stmt = stmt.where(KnowledgeArticle.category == category)
    return [(aid, float(r)) for aid, r in (await db.execute(stmt)).all()]


async def articles_by_ids(db: AsyncSession, ids: list[int]) -> dict[int, KnowledgeArticle]:
    if not ids:
        return {}
    rows = await db.scalars(select(KnowledgeArticle).where(KnowledgeArticle.id.in_(ids)))
    return {a.id: a for a in rows.unique().all()}


async def count_article_use(db: AsyncSession, ids: list[int]) -> None:
    if ids:
        await db.execute(
            update(KnowledgeArticle)
            .where(KnowledgeArticle.id.in_(ids))
            .values(usage_count=KnowledgeArticle.usage_count + 1, updated_at=KnowledgeArticle.updated_at)
        )
