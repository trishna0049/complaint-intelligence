"""Dashboard analytics, computed with SQL aggregates over the complaints table."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Complaint

NEGATIVE = ("Very Negative", "Negative")
SENTIMENTS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"]


def _pct_change(cur: float, prev: float) -> float | None:
    return None if prev == 0 else round((cur - prev) / prev * 100, 1)


# Small in-process cache: the dashboard scans the whole table, and writes call invalidate_cache().
_CACHE: dict[int, tuple[float, dict[str, Any]]] = {}
CACHE_SECONDS = 60


def invalidate_cache() -> None:
    _CACHE.clear()


def cached_dashboard(db: Session, days: int = 30) -> dict[str, Any]:
    hit = _CACHE.get(days)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    result = dashboard(db, days)
    _CACHE[days] = (time.monotonic(), result)
    return result


def dashboard(db: Session, days: int = 30, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    # Window starts at midnight UTC so the first day in the trend is a complete day.
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    prev_since = since - timedelta(days=days)
    in_window = Complaint.created_at >= since
    is_negative = Complaint.sentiment.in_(NEGATIVE)

    # ---------------- KPIs (current window vs the previous window of equal length) ----------------
    def kpis(start: datetime, end: datetime) -> dict[str, Any]:
        row = db.execute(
            select(
                func.count(),
                func.sum(case((Complaint.status != "Resolved", 1), else_=0)),
                func.sum(case((Complaint.priority.in_(("High", "Critical")), 1), else_=0)),
                func.sum(case((Complaint.priority == "Critical", 1), else_=0)),
                func.sum(case((is_negative, 1), else_=0)),
                func.count(Complaint.sentiment),
                func.avg(Complaint.csat_score),
                func.avg(Complaint.sentiment_score),
            ).where(Complaint.created_at >= start, Complaint.created_at < end)
        ).one()
        total, open_, high, critical, neg, with_sent, csat, sent_score = row
        return {
            "total": total or 0,
            "open": open_ or 0,
            "high_priority": high or 0,
            "critical": critical or 0,
            "negative_share": round((neg or 0) / with_sent, 4) if with_sent else None,
            "avg_csat": round(csat, 2) if csat is not None else None,
            "avg_sentiment_score": round(sent_score, 2) if sent_score is not None else None,
        }

    current = kpis(since, now + timedelta(seconds=1))
    previous = kpis(prev_since, since)
    # Only compare periods when the data fully covers the previous window; otherwise the change is an artifact.
    earliest = db.scalar(select(func.min(Complaint.created_at)))
    comparable = earliest is not None and earliest <= prev_since
    current["total_change_pct"] = _pct_change(current["total"], previous["total"]) if comparable else None
    current["high_priority_change_pct"] = (
        _pct_change(current["high_priority"], previous["high_priority"]) if comparable else None
    )
    current["needs_review"] = (
        db.scalar(select(func.count()).where(Complaint.needs_review.is_(True), Complaint.status != "Resolved")) or 0
    )
    current["open_high_priority"] = (
        db.scalar(
            select(func.count()).where(Complaint.status != "Resolved", Complaint.priority.in_(("High", "Critical")))
        )
        or 0
    )

    # ---------------- daily trend: volume + sentiment mix ----------------
    day = func.date(Complaint.created_at)
    trend_rows = db.execute(
        select(
            day.label("day"),
            func.count(),
            *[func.sum(case((Complaint.sentiment == s, 1), else_=0)) for s in SENTIMENTS],
            func.sum(case((Complaint.priority.in_(("High", "Critical")), 1), else_=0)),
            func.avg(Complaint.csat_score),
        )
        .where(in_window)
        .group_by(day)
        .order_by(day)
    ).all()
    trend = [
        {
            "date": r[0],
            "total": r[1],
            **{s: r[2 + i] or 0 for i, s in enumerate(SENTIMENTS)},
            "high_priority": r[7] or 0,
            "avg_csat": round(r[8], 2) if r[8] is not None else None,
        }
        for r in trend_rows
    ]

    # ---------------- breakdowns ----------------
    def breakdown(column: Any, limit: int | None = None) -> list[dict[str, Any]]:
        stmt = (
            select(
                column,
                func.count().label("n"),
                func.sum(case((is_negative, 1), else_=0)),
                func.count(Complaint.sentiment),
                func.sum(case((Complaint.priority.in_(("High", "Critical")), 1), else_=0)),
            )
            .where(in_window, column.is_not(None))
            .group_by(column)
            .order_by(func.count().desc())
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
            for name, n, neg, scored, high in db.execute(stmt).all()
        ]

    sentiment_dist = dict(
        db.execute(
            select(Complaint.sentiment, func.count())
            .where(in_window, Complaint.sentiment.is_not(None))
            .group_by(Complaint.sentiment)
        ).all()
    )

    # ---------------- high-priority open complaints ----------------
    rank = func.instr("LowMediumHighCritical", Complaint.priority)
    hot = db.scalars(
        select(Complaint)
        .where(Complaint.status != "Resolved", Complaint.priority.in_(("High", "Critical")))
        .order_by(rank.desc(), Complaint.created_at.desc())
        .limit(8)
    ).all()

    emerging = emerging_issues(db, now)
    return {
        "window_days": days,
        "generated_at": now.isoformat(),
        "kpis": current,
        "trend": trend,
        "categories": breakdown(Complaint.category),
        "intents": breakdown(Complaint.intent, limit=10),
        "channels": breakdown(Complaint.channel),
        "priorities": breakdown(Complaint.priority),
        "sentiment": [{"name": s, "count": sentiment_dist.get(s, 0)} for s in SENTIMENTS],
        "high_priority_open": [
            {
                "id": c.id,
                "reference": c.reference,
                "subject": c.subject,
                "category": c.category,
                "priority": c.priority,
                "sentiment": c.sentiment,
                "created_at": c.created_at.isoformat(),
            }
            for c in hot
        ],
        "emerging": emerging,
        "insights": build_insights(current, emerging),
    }


def emerging_issues(db: Session, now: datetime, min_count: int = 20) -> list[dict[str, Any]]:
    """Week-over-week change per category (last 7 days vs the 7 days before)."""
    week = now - timedelta(days=7)
    two_weeks = now - timedelta(days=14)
    rows = db.execute(
        select(
            Complaint.category,
            func.sum(case((Complaint.created_at >= week, 1), else_=0)),
            func.sum(case((Complaint.created_at < week, 1), else_=0)),
            func.sum(case(((Complaint.created_at >= week) & Complaint.sentiment.in_(NEGATIVE), 1), else_=0)),
            func.sum(case(((Complaint.created_at >= week) & Complaint.sentiment.is_not(None), 1), else_=0)),
        )
        .where(Complaint.created_at >= two_weeks, Complaint.category.is_not(None))
        .group_by(Complaint.category)
    ).all()
    out = []
    for name, this_week, last_week, neg, scored in rows:
        this_week, last_week = this_week or 0, last_week or 0
        if max(this_week, last_week) < min_count:
            continue
        out.append(
            {
                "category": name,
                "this_week": this_week,
                "last_week": last_week,
                "change_pct": _pct_change(this_week, last_week),
                "negative_share": round((neg or 0) / scored, 4) if scored else None,
            }
        )
    return sorted(out, key=lambda r: (r["change_pct"] is None, -(r["change_pct"] or 0)))


def build_insights(kpis: dict[str, Any], emerging: list[dict[str, Any]]) -> list[str]:
    """Plain-English observations generated from the numbers (deterministic, no LLM)."""
    notes: list[str] = []
    rising = [e for e in emerging if e["change_pct"] is not None and e["change_pct"] >= 15]
    if rising:
        top = rising[0]
        notes.append(
            f"{top['category']} complaints rose {top['change_pct']:.0f}% this week "
            f"({top['this_week']:,} vs {top['last_week']:,} the week before)."
        )
    falling = [e for e in emerging if e["change_pct"] is not None and e["change_pct"] <= -15]
    if falling:
        low = falling[-1]
        notes.append(f"{low['category']} complaints fell {abs(low['change_pct']):.0f}% week over week.")
    if kpis.get("negative_share") is not None:
        notes.append(f"{kpis['negative_share'] * 100:.0f}% of complaints with a sentiment score are negative.")
    if kpis.get("open_high_priority"):
        notes.append(f"{kpis['open_high_priority']:,} high or critical priority complaints are still open.")
    if kpis.get("total_change_pct") is not None:
        direction = "up" if kpis["total_change_pct"] >= 0 else "down"
        notes.append(f"Overall volume is {direction} {abs(kpis['total_change_pct']):.0f}% versus the previous period.")
    return notes or ["Not enough recent data for insights yet."]
