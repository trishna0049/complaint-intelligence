"""Analytics SQL over the complaints table (aggregates only — formatting lives in the service)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Complaint
from app.repositories.complaints import priority_rank

NEGATIVE = ("Very Negative", "Negative")
SENTIMENTS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"]
HIGH = ("High", "Critical")


async def kpis(db: AsyncSession, start: datetime, end: datetime) -> dict[str, Any]:
    is_negative = Complaint.sentiment.in_(NEGATIVE)
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Complaint.status != "Resolved"),
                func.count().filter(Complaint.priority.in_(HIGH)),
                func.count().filter(Complaint.priority == "Critical"),
                func.count().filter(is_negative),
                func.count(Complaint.sentiment),
                func.avg(Complaint.csat_score),
                func.avg(Complaint.sentiment_score),
            ).where(Complaint.created_at >= start, Complaint.created_at < end)
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
    return await db.scalar(select(func.min(Complaint.created_at)))


async def open_counts(db: AsyncSession) -> tuple[int, int]:
    """(open complaints needing review, open high/critical complaints)."""
    row = (
        await db.execute(
            select(
                func.count().filter(Complaint.needs_review.is_(True)),
                func.count().filter(Complaint.priority.in_(HIGH)),
            ).where(Complaint.status != "Resolved")
        )
    ).one()
    return row[0] or 0, row[1] or 0


async def daily_trend(db: AsyncSession, since: datetime) -> list[dict[str, Any]]:
    day = cast(Complaint.created_at, Date)
    rows = (
        await db.execute(
            select(
                day.label("day"),
                func.count(),
                *[func.count().filter(Complaint.sentiment == s) for s in SENTIMENTS],
                func.count().filter(Complaint.priority.in_(HIGH)),
                func.avg(Complaint.csat_score),
            )
            .where(Complaint.created_at >= since)
            .group_by(day)
            .order_by(day)
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
            func.count().filter(Complaint.sentiment.in_(NEGATIVE)),
            func.count(Complaint.sentiment),
            func.count().filter(Complaint.priority.in_(HIGH)),
        )
        .where(Complaint.created_at >= since, column.is_not(None))
        .group_by(column)
        .order_by(func.count().desc(), column)
    )
    if limit:
        stmt = stmt.limit(limit)
    return [
        {
            "name": name,
            "count": n,
            # share of complaints *with a sentiment score* that are negative (templated rows have none)
            "negative_share": round((neg or 0) / scored, 4) if scored else None,
            "high_priority": high or 0,
        }
        for name, n, neg, scored, high in (await db.execute(stmt)).all()
    ]


async def sentiment_distribution(db: AsyncSession, since: datetime) -> dict[str, int]:
    rows = await db.execute(
        select(Complaint.sentiment, func.count())
        .where(Complaint.created_at >= since, Complaint.sentiment.is_not(None))
        .group_by(Complaint.sentiment)
    )
    return {s: n for s, n in rows.all()}


async def open_high_priority(db: AsyncSession, limit: int = 8) -> list[Complaint]:
    rows = await db.scalars(
        select(Complaint)
        .where(Complaint.status != "Resolved", Complaint.priority.in_(HIGH))
        .order_by(priority_rank().desc(), Complaint.created_at.desc())
        .limit(limit)
    )
    return list(rows.all())


async def week_over_week(db: AsyncSession, week: datetime, two_weeks: datetime) -> list[tuple[Any, ...]]:
    this_week = Complaint.created_at >= week
    rows = await db.execute(
        select(
            Complaint.category,
            func.count().filter(this_week),
            func.count().filter(Complaint.created_at < week),
            func.count().filter(this_week & Complaint.sentiment.in_(NEGATIVE)),
            func.count().filter(this_week & Complaint.sentiment.is_not(None)),
        )
        .where(Complaint.created_at >= two_weeks, Complaint.category.is_not(None))
        .group_by(Complaint.category)
    )
    return [tuple(r) for r in rows.all()]
