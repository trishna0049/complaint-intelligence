"""Dashboard analytics: composes the SQL aggregates in repositories.analytics, cached in Redis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import cached_json, invalidate
from app.models import Complaint
from app.repositories import analytics as q

CACHE_NS = "analytics"
CACHE_SECONDS = 60


def _pct_change(cur: float, prev: float) -> float | None:
    return None if prev == 0 else round((cur - prev) / prev * 100, 1)


async def invalidate_cache() -> None:
    await invalidate(CACHE_NS)


async def cached_dashboard(db: AsyncSession, days: int = 30) -> dict[str, Any]:
    return await cached_json(CACHE_NS, f"dashboard:{days}", CACHE_SECONDS, lambda: dashboard(db, days))


async def dashboard(db: AsyncSession, days: int = 30, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    # Window starts at midnight UTC so the first day in the trend is a complete day.
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    prev_since = since - timedelta(days=days)

    current = await q.kpis(db, since, now + timedelta(seconds=1))
    previous = await q.kpis(db, prev_since, since)
    # Only compare periods when the data fully covers the previous window; otherwise the change is an artifact.
    earliest = await q.earliest_created(db)
    comparable = earliest is not None and earliest <= prev_since
    current["total_change_pct"] = _pct_change(current["total"], previous["total"]) if comparable else None
    current["high_priority_change_pct"] = (
        _pct_change(current["high_priority"], previous["high_priority"]) if comparable else None
    )
    current["needs_review"], current["open_high_priority"] = await q.open_counts(db)

    sentiment_dist = await q.sentiment_distribution(db, since)
    hot = await q.open_high_priority(db)
    emerging = await emerging_issues(db, now)
    return {
        "window_days": days,
        "generated_at": now.isoformat(),
        "kpis": current,
        "trend": await q.daily_trend(db, since),
        "categories": await q.breakdown(db, Complaint.category, since),
        "intents": await q.breakdown(db, Complaint.intent, since, limit=10),
        "channels": await q.breakdown(db, Complaint.channel, since),
        "priorities": await q.breakdown(db, Complaint.priority, since),
        "sentiment": [{"name": s, "count": sentiment_dist.get(s, 0)} for s in q.SENTIMENTS],
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


async def emerging_issues(db: AsyncSession, now: datetime, min_count: int = 20) -> list[dict[str, Any]]:
    """Week-over-week change per category (last 7 days vs the 7 days before)."""
    rows = await q.week_over_week(db, now - timedelta(days=7), now - timedelta(days=14))
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
    return sorted(out, key=lambda r: (r["change_pct"] is None, -(r["change_pct"] or 0), r["category"]))


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
