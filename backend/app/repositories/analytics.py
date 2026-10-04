"""Analytics SQL over the tickets table (aggregates only — composition and caching live in the service)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.repositories.tickets import priority_rank

NEGATIVE = ("Very Negative", "Negative")
SENTIMENTS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"]
HIGH = ("High", "Critical")


async def kpis(db: AsyncSession, start: datetime, end: datetime) -> dict[str, Any]:
    is_negative = Ticket.sentiment.in_(NEGATIVE)
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Ticket.status != "Resolved"),
                func.count().filter(Ticket.priority.in_(HIGH)),
                func.count().filter(Ticket.priority == "Critical"),
                func.count().filter(is_negative),
                func.count(Ticket.sentiment),
                func.avg(Ticket.csat_score),
                func.avg(Ticket.sentiment_score),
            ).where(Ticket.created_at >= start, Ticket.created_at < end)
        )
    ).one()
    total, open_, high, critical, neg, with_sent, csat, sent_score = row
    return {
        "total": total or 0,
        "open": open_ or 0,
        "high_priority": high or 0,
        "critical": critical or 0,
        "negative_share": round((neg or 0) / with_sent, 4) if with_sent else None,
        "avg_csat": round(float(csat), 2) if csat is not None else None,
        "avg_sentiment_score": round(float(sent_score), 2) if sent_score is not None else None,
    }


async def earliest_created(db: AsyncSession) -> datetime | None:
    return await db.scalar(select(func.min(Ticket.created_at)))


async def open_counts(db: AsyncSession) -> tuple[int, int]:
    """(open tickets needing review, open high/critical tickets)."""
    row = (
        await db.execute(
            select(
                func.count().filter(Ticket.needs_review.is_(True)),
                func.count().filter(Ticket.priority.in_(HIGH)),
            ).where(Ticket.status != "Resolved")
        )
    ).one()
    return row[0] or 0, row[1] or 0


async def trend(db: AsyncSession, since: datetime, granularity: str = "day") -> list[dict[str, Any]]:
    """Volume, sentiment mix, high-priority count and CSAT per day / ISO week / month."""
    if granularity not in ("day", "week", "month"):
        raise ValueError(granularity)
    bucket = cast(func.date_trunc(granularity, Ticket.created_at), Date)
    rows = (
        await db.execute(
            select(
                bucket.label("bucket"),
                func.count(),
                *[func.count().filter(Ticket.sentiment == s) for s in SENTIMENTS],
                func.count().filter(Ticket.priority.in_(HIGH)),
                func.avg(Ticket.csat_score),
            )
            .where(Ticket.created_at >= since)
            .group_by(bucket)
            .order_by(bucket)
        )
    ).all()
    return [
        {
            "date": r[0].isoformat(),
            "total": r[1],
            **{s: r[2 + i] or 0 for i, s in enumerate(SENTIMENTS)},
            "high_priority": r[7] or 0,
            "avg_csat": round(float(r[8]), 2) if r[8] is not None else None,
        }
        for r in rows
    ]


async def breakdown(db: AsyncSession, column: Any, since: datetime, limit: int | None = None) -> list[dict[str, Any]]:
    stmt = (
        select(
            column,
            func.count().label("n"),
            func.count().filter(Ticket.sentiment.in_(NEGATIVE)),
            func.count(Ticket.sentiment),
            func.count().filter(Ticket.priority.in_(HIGH)),
        )
        .where(Ticket.created_at >= since, column.is_not(None))
        .group_by(column)
        .order_by(func.count().desc(), column)
    )
    if limit:
        stmt = stmt.limit(limit)
    return [
        {
            "name": name,
            "count": n,
            # share of tickets *with a sentiment score* that are negative (templated rows have none)
            "negative_share": round((neg or 0) / scored, 4) if scored else None,
            "high_priority": high or 0,
        }
        for name, n, neg, scored, high in (await db.execute(stmt)).all()
    ]


async def sentiment_distribution(db: AsyncSession, since: datetime) -> dict[str, int]:
    rows = await db.execute(
        select(Ticket.sentiment, func.count())
        .where(Ticket.created_at >= since, Ticket.sentiment.is_not(None))
        .group_by(Ticket.sentiment)
    )
    return {s: n for s, n in rows.all()}


async def open_high_priority(db: AsyncSession, limit: int = 8) -> list[Ticket]:
    rows = await db.scalars(
        select(Ticket)
        .where(Ticket.status != "Resolved", Ticket.priority.in_(HIGH))
        .order_by(priority_rank().desc(), Ticket.created_at.desc())
        .limit(limit)
    )
    return list(rows.all())


async def week_over_week(db: AsyncSession, week: datetime, two_weeks: datetime) -> list[tuple[Any, ...]]:
    this_week = Ticket.created_at >= week
    rows = await db.execute(
        select(
            Ticket.category,
            func.count().filter(this_week),
            func.count().filter(Ticket.created_at < week),
            func.count().filter(this_week & Ticket.sentiment.in_(NEGATIVE)),
            func.count().filter(this_week & Ticket.sentiment.is_not(None)),
        )
        .where(Ticket.created_at >= two_weeks, Ticket.category.is_not(None))
        .group_by(Ticket.category)
    )
    return [tuple(r) for r in rows.all()]
