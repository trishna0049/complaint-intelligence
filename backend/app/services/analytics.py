"""Analytics: composes the SQL aggregates in repositories.analytics; every result is cached in Redis and the cache is
invalidated on every ticket write."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import cached_json, invalidate
from app.models import Ticket
from app.repositories import analytics as q

CACHE_NS = "analytics"
CACHE_SECONDS = 60


def _pct_change(cur: float, prev: float) -> float | None:
    return None if prev == 0 else round((cur - prev) / prev * 100, 1)


def window(days: int, now: datetime | None = None) -> tuple[datetime, datetime, datetime]:
    """(now, start of window, start of the previous window). Windows start at midnight UTC so the first day in a
    trend is a complete day."""
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return now, since, since - timedelta(days=days)


async def invalidate_cache() -> None:
    await invalidate(CACHE_NS)


# ------------------------------------------------------------------------------------------- overview
async def overview(db: AsyncSession, days: int = 30) -> dict[str, Any]:
    return await cached_json(CACHE_NS, f"overview:{days}", CACHE_SECONDS, lambda: _overview(db, days))


async def _overview(db: AsyncSession, days: int, now: datetime | None = None) -> dict[str, Any]:
    now, since, prev_since = window(days, now)
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
    hot = await q.open_high_priority(db)
    emerging = await _emerging(db, now)
    return {
        "window_days": days,
        "generated_at": now.isoformat(),
        "kpis": current,
        "high_priority_open": [
            {
                "id": t.id,
                "ticket_number": t.ticket_number,
                "subject": t.subject,
                "category": t.category,
                "priority": t.priority,
                "sentiment": t.sentiment,
                "created_at": t.created_at.isoformat(),
            }
            for t in hot
        ],
        "insights": build_insights(current, emerging) + await operational_insights(db, now),
    }


# ------------------------------------------------------------------------------------------- trends
async def trends(db: AsyncSession, days: int = 30, granularity: str = "day") -> dict[str, Any]:
    async def compute() -> dict[str, Any]:
        _, since, _ = window(days)
        return {"window_days": days, "granularity": granularity, "points": await q.trend(db, since, granularity)}

    return await cached_json(CACHE_NS, f"trends:{days}:{granularity}", CACHE_SECONDS, compute)


# ------------------------------------------------------------------------------------------- categories
async def categories(db: AsyncSession, days: int = 30) -> dict[str, Any]:
    async def compute() -> dict[str, Any]:
        now, since, _ = window(days)
        until = now + timedelta(seconds=1)
        sentiment_dist = await q.sentiment_distribution(db, since)
        return {
            "window_days": days,
            "categories": await q.breakdown(db, Ticket.category, since),
            "intents": await q.breakdown(db, Ticket.intent, since, limit=10),
            "channels": await q.breakdown(db, Ticket.channel, since),
            "priorities": await q.breakdown(db, Ticket.priority, since),
            "sentiment": [{"name": s, "count": sentiment_dist.get(s, 0)} for s in q.SENTIMENTS],
            # Rates by channel, city and product (spec), with how many tickets carry the field ("data coverage").
            "channel_rates": await q.segment_rates(db, Ticket.channel, since, until),
            "city_rates": await q.segment_rates(db, Ticket.city, since, until, limit=15),
            "product_rates": await q.segment_rates(db, Ticket.product, since, until, limit=15),
        }

    return await cached_json(CACHE_NS, f"categories:{days}", CACHE_SECONDS, compute)


# ------------------------------------------------------------------------------------------- emerging
async def emerging(db: AsyncSession) -> dict[str, Any]:
    async def compute() -> dict[str, Any]:
        now = datetime.now(UTC)
        return {"generated_at": now.isoformat(), "emerging": await _emerging(db, now)}

    return await cached_json(CACHE_NS, "emerging", CACHE_SECONDS, compute)


async def _emerging(db: AsyncSession, now: datetime, min_count: int = 20) -> list[dict[str, Any]]:
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
        notes.append(f"{kpis['negative_share'] * 100:.0f}% of tickets with a sentiment score are negative.")
    if kpis.get("open_high_priority"):
        notes.append(f"{kpis['open_high_priority']:,} high or critical priority tickets are still open.")
    if kpis.get("total_change_pct") is not None:
        direction = "up" if kpis["total_change_pct"] >= 0 else "down"
        notes.append(f"Overall volume is {direction} {abs(kpis['total_change_pct']):.0f}% versus the previous period.")
    return notes or ["Not enough recent data for insights yet."]


# ------------------------------------------------------------------------------------------- SLA
async def sla(db: AsyncSession, days: int = 30, granularity: str = "day") -> dict[str, Any]:
    return await cached_json(CACHE_NS, f"sla:{days}:{granularity}", CACHE_SECONDS, lambda: _sla(db, days, granularity))


async def _sla(db: AsyncSession, days: int, granularity: str, now: datetime | None = None) -> dict[str, Any]:
    from app.models import Team

    now, since, _ = window(days, now)
    until = now + timedelta(seconds=1)
    summary = await q.sla_summary(db, since, until, now)
    return {
        "window_days": days,
        "generated_at": now.isoformat(),
        **summary,
        "by_priority": await q.sla_by(db, since, until, Ticket.priority),
        "by_category": await q.sla_by(db, since, until, Ticket.category),
        "by_team": await q.sla_by_team(db, since, until, Team),
        "trend": await q.sla_trend(db, since, until, granularity),
    }


# ------------------------------------------------------------------------------------------- performance
async def performance(db: AsyncSession, days: int = 30, granularity: str = "day") -> dict[str, Any]:
    return await cached_json(
        CACHE_NS, f"performance:{days}:{granularity}", CACHE_SECONDS, lambda: _performance(db, days, granularity)
    )


async def _performance(db: AsyncSession, days: int, granularity: str, now: datetime | None = None) -> dict[str, Any]:
    now, since, _ = window(days, now)
    until = now + timedelta(seconds=1)
    return {
        "window_days": days,
        "granularity": granularity,
        "generated_at": now.isoformat(),
        **await q.timing(db, since, until),
        "by_channel": await q.timing_by(db, since, until, Ticket.channel),
        "by_priority": await q.timing_by(db, since, until, Ticket.priority),
        "trend": await q.timing_trend(db, since, until, granularity),
        "repeat": await q.repeat_complaints(db, since, until),
    }


# ------------------------------------------------------------------------------------------- workload
async def workload(db: AsyncSession) -> dict[str, Any]:
    async def compute() -> dict[str, Any]:
        now = datetime.now(UTC)
        teams = await q.team_workload(db, now)
        return {
            "generated_at": now.isoformat(),
            "teams": teams,
            "agents": await q.agent_workload(db, now),
            "totals": {
                "open": sum(t["open"] for t in teams),
                "unassigned": sum(t["unassigned"] for t in teams),
                "at_risk": sum(t["at_risk"] for t in teams),
                "agents": sum(t["agents"] for t in teams),
            },
        }

    return await cached_json(CACHE_NS, "workload", CACHE_SECONDS, compute)


# ------------------------------------------------------------------------------------------- my stats
async def my_stats(db: AsyncSession, user: Any) -> dict[str, Any]:
    """An agent's own numbers (spec: "My stats": open tickets, SLA at risk, resolved this week). Not cached: it must
    move the moment the agent resolves something."""
    from sqlalchemy import func, select

    from app.domain.lifecycle import OPEN_STATUSES

    now = datetime.now(UTC)
    stats = await q.my_stats(db, user.id, now)
    backlog = None
    if user.team_id:
        backlog = await db.scalar(
            select(func.count()).where(
                Ticket.team_id == user.team_id,
                Ticket.assignee_id.is_(None),
                Ticket.status.in_([s.value for s in OPEN_STATUSES]),
            )
        )
    return {**stats, "team_unassigned": backlog, "generated_at": now.isoformat()}


# ------------------------------------------------------------------------------------------- operational insights
async def operational_insights(db: AsyncSession, now: datetime) -> list[str]:
    """Plain-English notes on SLA, response times and workload for the last 7 days (deterministic, no LLM)."""
    since = now - timedelta(days=7)
    until = now + timedelta(seconds=1)
    from app.models import Team

    notes: list[str] = []
    teams = [t for t in await q.sla_by_team(db, since, until, Team) if t["with_sla"] >= 20 and t["breach_rate"]]
    if teams:
        worst = teams[0]
        notes.append(
            f"{worst['name']} has the highest SLA breach rate this week: {worst['breach_rate'] * 100:.0f}% "
            f"of {worst['with_sla']:,} tickets."
        )
    channels = [c for c in await q.timing_by(db, since, until, Ticket.channel) if c["tickets"] >= 20]
    timed = [c for c in channels if c["median_first_response_minutes"] is not None]
    if len(timed) >= 2:
        slow = max(timed, key=lambda c: c["median_first_response_minutes"])
        fast = min(timed, key=lambda c: c["median_first_response_minutes"])
        if slow["median_first_response_minutes"] > fast["median_first_response_minutes"]:
            notes.append(
                f"{slow['name']} contacts wait longest for a first response (median "
                f"{slow['median_first_response_minutes']:.0f} min vs {fast['median_first_response_minutes']:.0f} min "
                f"for {fast['name']})."
            )
    backlog = [t for t in await q.team_workload(db, now) if t["unassigned"] > 0]
    if backlog:
        top = max(backlog, key=lambda t: t["unassigned"])
        n = top["unassigned"]
        notes.append(f"{top['team']} has the largest unassigned backlog: {n:,} open ticket{'' if n == 1 else 's'}.")
    return notes
