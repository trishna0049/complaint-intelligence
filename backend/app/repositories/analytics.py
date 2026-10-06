"""Analytics SQL over the tickets table (aggregates only — composition and caching live in the service)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.lifecycle import OPEN_STATUSES
from app.models import Ticket
from app.repositories.tickets import priority_rank

NEGATIVE = ("Very Negative", "Negative")
SENTIMENTS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"]
HIGH = ("High", "Critical")
OPEN = sorted(s.value for s in OPEN_STATUSES)


async def kpis(db: AsyncSession, start: datetime, end: datetime) -> dict[str, Any]:
    is_negative = Ticket.sentiment.in_(NEGATIVE)
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Ticket.status.in_(OPEN)),
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
            ).where(Ticket.status.in_(OPEN))
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
        .where(Ticket.status.in_(OPEN), Ticket.priority.in_(HIGH))
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


# ------------------------------------------------------------------------------------------------ SLA
def _at_risk(now: datetime) -> Any:
    """Running clocks with 80 % or more used and no breach yet."""
    warn_at = Ticket.sla_deadline - func.make_interval(0, 0, 0, 0, 0, 0, Ticket.sla_target_seconds * 0.2)
    return (Ticket.sla_status == "running") & (warn_at <= now) & Ticket.sla_breached_at.is_(None)


async def sla_summary(db: AsyncSession, start: datetime, end: datetime, now: datetime) -> dict[str, Any]:
    """Tickets created in [start, end) that had an SLA clock: how many breached, how fast they were resolved."""
    has_sla = Ticket.sla_started_at.is_not(None)
    breached = Ticket.sla_breached_at.is_not(None)
    finished = Ticket.sla_stopped_at.is_not(None)
    resolution_minutes = (
        func.extract("epoch", Ticket.sla_stopped_at - Ticket.sla_started_at) - Ticket.sla_paused_seconds
    ) / 60
    row = (
        await db.execute(
            select(
                func.count().filter(has_sla),
                func.count().filter(breached),
                func.count().filter(finished & ~breached),
                func.avg(resolution_minutes).filter(finished),
                func.avg(Ticket.sla_target_seconds / 60.0).filter(has_sla),
            ).where(Ticket.created_at >= start, Ticket.created_at < end)
        )
    ).one()
    open_now = (
        await db.execute(
            select(
                func.count().filter(_at_risk(now)),
                func.count().filter(breached),
                func.count().filter(Ticket.sla_status == "paused"),
                func.count().filter(Ticket.sla_status == "running"),
            ).where(Ticket.status.in_(OPEN))
        )
    ).one()
    total, n_breached, n_met = row[0] or 0, row[1] or 0, row[2] or 0
    return {
        "with_sla": total,
        "breached": n_breached,
        "met": n_met,
        "breach_rate": round(n_breached / total, 4) if total else None,
        "avg_resolution_minutes": round(float(row[3]), 1) if row[3] is not None else None,
        "avg_target_minutes": round(float(row[4]), 1) if row[4] is not None else None,
        "open": {
            "at_risk": open_now[0] or 0,
            "breached": open_now[1] or 0,
            "paused": open_now[2] or 0,
            "running": open_now[3] or 0,
        },
    }


async def sla_by(db: AsyncSession, start: datetime, end: datetime, column: Any) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(
            column,
            func.count().filter(Ticket.sla_started_at.is_not(None)),
            func.count().filter(Ticket.sla_breached_at.is_not(None)),
        )
        .where(Ticket.created_at >= start, Ticket.created_at < end, Ticket.sla_started_at.is_not(None))
        .group_by(column)
    )
    out = [
        {"name": name or "—", "with_sla": n, "breached": b, "breach_rate": round(b / n, 4) if n else None}
        for name, n, b in rows.all()
    ]
    return sorted(out, key=lambda r: (-(r["breach_rate"] or 0), -r["with_sla"]))


async def sla_trend(db: AsyncSession, start: datetime, end: datetime, granularity: str) -> list[dict[str, Any]]:
    bucket = func.date_trunc(granularity, Ticket.created_at)
    rows = await db.execute(
        select(
            bucket,
            func.count().filter(Ticket.sla_started_at.is_not(None)),
            func.count().filter(Ticket.sla_breached_at.is_not(None)),
        )
        .where(Ticket.created_at >= start, Ticket.created_at < end)
        .group_by(bucket)
        .order_by(bucket)
    )
    return [
        {"date": b.date().isoformat(), "with_sla": n, "breached": x, "breach_rate": round(x / n, 4) if n else None}
        for b, n, x in rows.all()
    ]


async def sla_by_team(db: AsyncSession, start: datetime, end: datetime, team_model: Any) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(
            team_model.name,
            func.count(),
            func.count().filter(Ticket.sla_breached_at.is_not(None)),
        )
        .join(team_model, team_model.id == Ticket.team_id)
        .where(Ticket.created_at >= start, Ticket.created_at < end, Ticket.sla_started_at.is_not(None))
        .group_by(team_model.name)
    )
    out = [
        {"name": name, "with_sla": n, "breached": b, "breach_rate": round(b / n, 4) if n else None}
        for name, n, b in rows.all()
    ]
    return sorted(out, key=lambda r: (-(r["breach_rate"] or 0), -r["with_sla"]))


# ------------------------------------------------------------------------------------------------ timing
def _minutes(later: Any) -> Any:
    return func.extract("epoch", later - Ticket.created_at) / 60


FIRST_RESPONSE = _minutes(Ticket.first_response_at)
RESOLUTION = _minutes(Ticket.resolved_at)


def _pct(expr: Any, q_: float) -> Any:
    return func.percentile_cont(q_).within_group(expr)


async def timing(db: AsyncSession, start: datetime, end: datetime) -> dict[str, Any]:
    """First-response and resolution times (minutes) for tickets created in the window."""
    responded = Ticket.first_response_at >= Ticket.created_at
    resolved = Ticket.resolved_at >= Ticket.created_at
    window_ = (Ticket.created_at >= start) & (Ticket.created_at < end)
    fr = (
        await db.execute(
            select(func.count(), func.avg(FIRST_RESPONSE), _pct(FIRST_RESPONSE, 0.5), _pct(FIRST_RESPONSE, 0.9)).where(
                window_, responded
            )
        )
    ).one()
    res = (
        await db.execute(
            select(func.count(), func.avg(RESOLUTION), _pct(RESOLUTION, 0.5), _pct(RESOLUTION, 0.9)).where(
                window_, resolved
            )
        )
    ).one()
    total = await db.scalar(select(func.count()).where(window_)) or 0

    def pack(row: Any) -> dict[str, Any]:
        n, avg, median, p90 = row
        return {
            "count": n or 0,
            "coverage": round((n or 0) / total, 4) if total else None,
            "avg_minutes": round(float(avg), 1) if avg is not None else None,
            "median_minutes": round(float(median), 1) if median is not None else None,
            "p90_minutes": round(float(p90), 1) if p90 is not None else None,
        }

    return {"tickets": total, "first_response": pack(fr), "resolution": pack(res)}


async def timing_trend(db: AsyncSession, start: datetime, end: datetime, granularity: str) -> list[dict[str, Any]]:
    bucket = func.date_trunc(granularity, Ticket.created_at)
    rows = await db.execute(
        select(
            bucket,
            _pct(FIRST_RESPONSE, 0.5).filter(Ticket.first_response_at >= Ticket.created_at),
            _pct(RESOLUTION, 0.5).filter(Ticket.resolved_at >= Ticket.created_at),
            func.count(),
        )
        .where(Ticket.created_at >= start, Ticket.created_at < end)
        .group_by(bucket)
        .order_by(bucket)
    )
    return [
        {
            "date": b.date().isoformat(),
            "median_first_response_minutes": round(float(f), 1) if f is not None else None,
            "median_resolution_minutes": round(float(r), 1) if r is not None else None,
            "tickets": n,
        }
        for b, f, r, n in rows.all()
    ]


async def timing_by(db: AsyncSession, start: datetime, end: datetime, column: Any) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(
            column,
            func.count(),
            _pct(FIRST_RESPONSE, 0.5).filter(Ticket.first_response_at >= Ticket.created_at),
            _pct(RESOLUTION, 0.5).filter(Ticket.resolved_at >= Ticket.created_at),
        )
        .where(Ticket.created_at >= start, Ticket.created_at < end, column.is_not(None))
        .group_by(column)
        .order_by(func.count().desc())
    )
    return [
        {
            "name": name,
            "tickets": n,
            "median_first_response_minutes": round(float(f), 1) if f is not None else None,
            "median_resolution_minutes": round(float(r), 1) if r is not None else None,
        }
        for name, n, f, r in rows.all()
    ]


# ------------------------------------------------------------------------------------------------ repeat complaints
REPEAT_WINDOW_DAYS = 30


async def repeat_complaints(db: AsyncSession, start: datetime, end: datetime) -> dict[str, Any]:
    """A complaint counts as a repeat when the text says the customer already contacted us (rule-based cue) or, for a
    known customer, when they had another ticket in the previous 30 days."""
    from sqlalchemy import and_, exists
    from sqlalchemy.orm import aliased

    earlier = aliased(Ticket)
    same_customer = exists().where(
        and_(
            earlier.customer_id == Ticket.customer_id,
            earlier.id != Ticket.id,
            earlier.created_at < Ticket.created_at,
            earlier.created_at >= Ticket.created_at - func.make_interval(0, 0, 0, REPEAT_WINDOW_DAYS),
        )
    )
    cue = Ticket.entities["repeat_contact"].as_boolean().is_(True)
    known = Ticket.customer_id.is_not(None)
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Ticket.description_source != "template"),
                func.count().filter(cue),
                func.count().filter(known),
                func.count().filter(known & same_customer),
                func.count().filter(cue | (known & same_customer)),
            ).where(Ticket.created_at >= start, Ticket.created_at < end)
        )
    ).one()
    total, with_text, cues, n_known, returning, repeats = (x or 0 for x in row)
    judged = max(with_text, n_known)
    return {
        "tickets": total,
        "with_text": with_text,
        "repeat_cue": cues,
        "known_customer": n_known,
        "returning_customer": returning,
        "repeats": repeats,
        # Of the tickets we can judge (customer text or a known customer), the share that are repeats.
        "repeat_rate": round(repeats / judged, 4) if judged else None,
        "window_days": REPEAT_WINDOW_DAYS,
    }


# ------------------------------------------------------------------------------------------------ segments with rates
async def segment_rates(
    db: AsyncSession, column: Any, start: datetime, end: datetime, limit: int | None = None
) -> dict[str, Any]:
    """Per-segment rates (negative sentiment, high priority, SLA breach, CSAT) plus how many tickets carry the field."""
    window_ = (Ticket.created_at >= start) & (Ticket.created_at < end)
    total = await db.scalar(select(func.count()).where(window_)) or 0
    stmt = (
        select(
            column,
            func.count(),
            func.count().filter(Ticket.sentiment.in_(NEGATIVE)),
            func.count(Ticket.sentiment),
            func.count().filter(Ticket.priority.in_(HIGH)),
            func.count().filter(Ticket.sla_breached_at.is_not(None)),
            func.count().filter(Ticket.sla_started_at.is_not(None)),
            func.avg(Ticket.csat_score),
        )
        .where(window_, column.is_not(None))
        .group_by(column)
        .order_by(func.count().desc(), column)
    )
    if limit:
        stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()
    covered = await db.scalar(select(func.count()).where(window_, column.is_not(None))) or 0
    return {
        "coverage": round(covered / total, 4) if total else None,
        "with_value": covered,
        "items": [
            {
                "name": name,
                "count": n,
                "negative_share": round(neg / scored, 4) if scored else None,
                "high_priority_share": round(high / n, 4) if n else None,
                "breach_rate": round(breached / with_sla, 4) if with_sla else None,
                "avg_csat": round(float(csat), 2) if csat is not None else None,
            }
            for name, n, neg, scored, high, breached, with_sla, csat in rows
        ],
    }


# ------------------------------------------------------------------------------------------------ workload
async def team_workload(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    from datetime import timedelta

    from app.models import Team, User

    week_ago = now - timedelta(days=7)
    agents = dict(
        (
            await db.execute(
                select(User.team_id, func.count())
                .where(User.role == "AGENT", User.is_active.is_(True), User.team_id.is_not(None))
                .group_by(User.team_id)
            )
        ).all()
    )
    rows = await db.execute(
        select(
            Team.id,
            Team.name,
            func.count(Ticket.id).filter(Ticket.status.in_(OPEN)),
            func.count(Ticket.id).filter(Ticket.status.in_(OPEN) & Ticket.assignee_id.is_(None)),
            func.count(Ticket.id).filter(_at_risk(now)),
            func.count(Ticket.id).filter(Ticket.status.in_(OPEN) & Ticket.sla_breached_at.is_not(None)),
            func.count(Ticket.id).filter(Ticket.created_at >= week_ago),
            func.count(Ticket.id).filter(Ticket.resolved_at >= week_ago),
        )
        .outerjoin(Ticket, Ticket.team_id == Team.id)
        .group_by(Team.id, Team.name)
    )
    out = []
    for tid, name, open_, unassigned, risk, breached, created, resolved in rows.all():
        n_agents = agents.get(tid, 0)
        out.append(
            {
                "team_id": tid,
                "team": name,
                "agents": n_agents,
                "open": open_,
                "unassigned": unassigned,
                "open_per_agent": round(open_ / n_agents, 2) if n_agents else None,
                "at_risk": risk,
                "breached_open": breached,
                "created_7d": created,
                "resolved_7d": resolved,
            }
        )
    return sorted(out, key=lambda r: (-r["open"], r["team"]))


async def agent_workload(db: AsyncSession, now: datetime, limit: int = 15) -> list[dict[str, Any]]:
    from datetime import timedelta

    from app.models import Team, User

    week_ago = now - timedelta(days=7)
    rows = await db.execute(
        select(
            User.id,
            User.name,
            Team.name,
            func.count(Ticket.id).filter(Ticket.status.in_(OPEN)),
            func.count(Ticket.id).filter(_at_risk(now)),
            func.count(Ticket.id).filter(Ticket.status.in_(OPEN) & Ticket.sla_breached_at.is_not(None)),
            func.count(Ticket.id).filter(Ticket.resolved_at >= week_ago),
            _pct(RESOLUTION, 0.5).filter(Ticket.resolved_at >= week_ago),
        )
        .join(Ticket, Ticket.assignee_id == User.id)
        .outerjoin(Team, Team.id == User.team_id)
        .where(User.role == "AGENT")
        .group_by(User.id, User.name, Team.name)
        .having(func.count(Ticket.id).filter(Ticket.status.in_(OPEN) | (Ticket.resolved_at >= week_ago)) > 0)
        .order_by(func.count(Ticket.id).filter(Ticket.status.in_(OPEN)).desc(), User.name)
        .limit(limit)
    )
    return [
        {
            "user_id": uid,
            "name": name,
            "team": team,
            "open": open_,
            "at_risk": risk,
            "breached_open": breached,
            "resolved_7d": resolved,
            "median_resolution_minutes_7d": round(float(med), 1) if med is not None else None,
        }
        for uid, name, team, open_, risk, breached, resolved, med in rows.all()
    ]


# ------------------------------------------------------------------------------------------------ my stats
async def my_stats(db: AsyncSession, user_id: int, now: datetime) -> dict[str, Any]:
    from datetime import timedelta

    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    last_week = week_start - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    mine = Ticket.assignee_id == user_id
    row = (
        await db.execute(
            select(
                func.count().filter(Ticket.status.in_(OPEN)),
                func.count().filter(_at_risk(now)),
                func.count().filter(Ticket.status.in_(OPEN) & Ticket.sla_breached_at.is_not(None)),
                func.count().filter(Ticket.resolved_at >= week_start),
                func.count().filter((Ticket.resolved_at >= last_week) & (Ticket.resolved_at < week_start)),
                _pct(RESOLUTION, 0.5).filter(Ticket.resolved_at >= week_start),
                func.count().filter(
                    (Ticket.resolved_at >= week_start)
                    & Ticket.sla_breached_at.is_(None)
                    & Ticket.sla_started_at.is_not(None)
                ),
                func.count().filter((Ticket.resolved_at >= week_start) & Ticket.sla_started_at.is_not(None)),
                func.avg(Ticket.csat_score).filter(Ticket.resolved_at >= month_ago),
                func.count().filter(Ticket.status == "WAITING_CUSTOMER"),
            ).where(mine)
        )
    ).one()
    open_, risk, breached, done_week, done_last, median, met, with_sla, csat, waiting = row
    return {
        "open": open_ or 0,
        "sla_at_risk": risk or 0,
        "sla_breached_open": breached or 0,
        "waiting_on_customer": waiting or 0,
        "resolved_this_week": done_week or 0,
        "resolved_last_week": done_last or 0,
        "median_resolution_minutes_this_week": round(float(median), 1) if median is not None else None,
        "sla_met_rate_this_week": round(met / with_sla, 4) if with_sla else None,
        "avg_csat_30d": round(float(csat), 2) if csat is not None else None,
        "week_start": week_start.isoformat(),
    }
