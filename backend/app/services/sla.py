"""SLA engine: applies the clock maths (app.domain.sla) to tickets, driven by the SLA worker.

* ai.analysis.completed -> start: the most specific active policy for the ticket's priority (+ category) sets the
  target; the clock starts at the ticket's creation (the customer has been waiting since then).
* ticket.updated        -> WAITING_CUSTOMER pauses (deadline moves out), leaving it resumes; a reopen resumes the
  clock without counting the time the ticket was resolved; a new priority/category re-targets.
* ticket.resolved       -> stop: met, or breached if the deadline had passed.
* scan (every SLA_SCAN_SECONDS) -> sla.warning at 80 %, sla.breached at 100 %, each exactly once per ticket.
* sla.breached          -> automatic escalation (and, in step 10, admin alerts).

Every change is logged in sla_events and on the ticket timeline (sla_warning / sla_breached also go to Kafka).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.domain import sla as clockwork
from app.domain.lifecycle import OPEN_STATUSES, TRANSITIONS, Action, Status
from app.models import SlaEvent, SlaPolicy, Ticket
from app.repositories import tickets as tickets_repo
from app.services import timeline

log = logging.getLogger("app.sla")
SCAN_BATCH = 200


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------------------------------------ clock <-> ticket
def clock_of(t: Ticket) -> clockwork.Clock | None:
    if t.sla_started_at is None or not t.sla_target_seconds:
        return None
    return clockwork.Clock(
        started_at=t.sla_started_at,
        target_seconds=t.sla_target_seconds,
        paused_seconds=t.sla_paused_seconds or 0,
        paused_since=t.sla_paused_at,
        stopped_at=t.sla_stopped_at,
        breached_at=t.sla_breached_at,
    )


def _store(t: Ticket, clock: clockwork.Clock, now: datetime) -> None:
    t.sla_target_seconds = clock.target_seconds
    t.sla_started_at = clock.started_at
    t.sla_paused_seconds = clock.paused_seconds
    t.sla_paused_at = clock.paused_since
    t.sla_stopped_at = clock.stopped_at
    t.sla_deadline = clock.deadline(now)
    if t.sla_breached_at is not None:
        t.sla_status = "breached"  # sticky: a breach is never undone
    elif clock.stopped_at is not None:
        if clock.elapsed(now) <= clock.target_seconds:
            t.sla_status = "met"
        else:  # resolved late before the scanner caught it: the breach happened at the deadline
            t.sla_status, t.sla_breached_at = "breached", clock.deadline(now)
    else:
        t.sla_status = "paused" if clock.paused_since is not None else "running"


def _log(db: AsyncSession, t: Ticket, kind: str, **meta: Any) -> None:
    db.add(SlaEvent(ticket_id=t.id, event_type=kind, deadline=t.sla_deadline, metadata_=meta or None))
    deadline = t.sla_deadline.isoformat() if t.sla_deadline else None
    timeline.record(db, t, f"sla_{kind}", None, deadline=deadline, **meta)


def view(t: Ticket, now: datetime | None = None) -> dict[str, Any]:
    """What the UI shows: state (incl. at_risk), deadline, remaining, the share used."""
    now = now or _now()
    clock = clock_of(t)
    if clock is None:
        return {
            "state": "none",
            "deadline": None,
            "remaining_seconds": None,
            "ratio": None,
            "target_seconds": None,
            "paused": False,
            "started_at": None,
            "breached_at": None,
            "warned_at": None,
        }
    return {
        "state": clockwork.SlaState.BREACHED.value if t.sla_status == "breached" else clock.state(now).value,
        "deadline": clock.deadline(now),
        "remaining_seconds": round(clock.remaining(now)),
        "ratio": round(clock.ratio(now), 4),
        "target_seconds": clock.target_seconds,
        "paused": clock.paused_since is not None,
        "started_at": clock.started_at,
        "breached_at": t.sla_breached_at,
        "warned_at": t.sla_warned_at,
    }


# ------------------------------------------------------------------------------------------------ policies
async def policy_for(db: AsyncSession, priority: str | None, category: str | None) -> SlaPolicy | None:
    """The category-specific policy for this priority if there is one, else the priority's default."""
    if not priority:
        return None
    rows = (
        await db.scalars(
            select(SlaPolicy).where(
                SlaPolicy.is_active.is_(True),
                SlaPolicy.priority == priority,
                or_(SlaPolicy.category == category, SlaPolicy.category.is_(None)),
            )
        )
    ).all()
    return next((p for p in rows if p.category is not None), None) or next(iter(rows), None)


def _target(policy: SlaPolicy) -> int:
    return clockwork.target_seconds(policy.target_minutes, get_settings().sla_speedup)


# ------------------------------------------------------------------------------------------------ worker handlers
async def start(db: AsyncSession, ticket_id: int) -> None:
    t = await tickets_repo.get(db, ticket_id, for_update=True)
    if t is None or t.sla_started_at is not None or Status(t.status) not in OPEN_STATUSES or t.status == Status.NEW:
        return
    policy = await policy_for(db, t.priority, t.category)
    if policy is None:
        return
    now = _now()
    clock = clockwork.Clock(started_at=t.created_at, target_seconds=_target(policy))
    if t.status == Status.WAITING_CUSTOMER:
        clock = clockwork.pause(clock, now)
    t.sla_policy_id = policy.id
    _store(t, clock, now)
    _log(db, t, "started", policy=policy.name, target_minutes=policy.target_minutes)


async def on_status_change(db: AsyncSession, ticket_id: int, old: str | None, new: str | None) -> None:
    t = await tickets_repo.get(db, ticket_id, for_update=True)
    clock = clock_of(t) if t else None
    if t is None or clock is None or old == new:
        return
    now = _now()
    if new == Status.RESOLVED:
        _store(t, clockwork.stop(clock, now), now)
        _log(db, t, "stopped", outcome=t.sla_status)
    elif new == Status.WAITING_CUSTOMER:
        _store(t, clockwork.pause(clock, now), now)
        _log(db, t, "paused")
    elif old == Status.WAITING_CUSTOMER and new in {s.value for s in OPEN_STATUSES}:
        _store(t, clockwork.resume(clock, now), now)
        _log(db, t, "resumed")
    elif old in (Status.RESOLVED, Status.CLOSED) and new in {s.value for s in OPEN_STATUSES}:  # reopened
        _store(t, clockwork.resume(clock, now), now)
        _log(db, t, "resumed", reopened=True)


async def retarget(db: AsyncSession, ticket_id: int) -> None:
    """A category correction can change the priority — and with it the policy."""
    t = await tickets_repo.get(db, ticket_id, for_update=True)
    clock = clock_of(t) if t else None
    if t is None or clock is None or clock.stopped_at is not None:
        return
    policy = await policy_for(db, t.priority, t.category)
    if policy is None or (policy.id == t.sla_policy_id and _target(policy) == clock.target_seconds):
        return
    now = _now()
    t.sla_policy_id = policy.id
    _store(t, clockwork.retarget(clock, _target(policy)), now)
    _log(db, t, "retargeted", policy=policy.name, target_minutes=policy.target_minutes)


async def escalate_on_breach(db: AsyncSession, ticket_id: int) -> None:
    from app.services import tickets as tickets_svc  # local: tickets imports timeline, which this module uses

    t = await tickets_repo.get(db, ticket_id, for_update=True)
    if t is None or Status(t.status) not in TRANSITIONS[Action.ESCALATE].sources:
        return  # already escalated, resolved or closed
    policy = await db.get(SlaPolicy, t.sla_policy_id) if t.sla_policy_id else None
    reason = f"SLA breached ({policy.name})" if policy else "SLA breached"
    tickets_svc.stage_escalation(db, t, None, reason, auto=True)


# ------------------------------------------------------------------------------------------------ scanner
def due_clause(now: datetime) -> Any:
    """Running clocks that reached 80 % (not warned yet) or 100 % (not breached yet)."""
    warn_at = Ticket.sla_deadline - func.make_interval(
        0, 0, 0, 0, 0, 0, Ticket.sla_target_seconds * (1 - clockwork.WARNING_RATIO)
    )
    return and_(
        Ticket.sla_status == "running",
        or_(
            and_(Ticket.sla_warned_at.is_(None), warn_at <= now),
            and_(Ticket.sla_breached_at.is_(None), Ticket.sla_deadline <= now),
        ),
    )


async def scan_once(now: datetime | None = None) -> dict[str, int]:
    """Fire due warnings and breaches (once each: the row lock + the warned/breached timestamps make it safe to run
    several scanners). Returns the counts. The events go through the outbox like any other."""
    from app.events import bus

    now = now or _now()
    counts = {"warning": 0, "breached": 0}
    async with SessionLocal() as db:
        due = (
            (
                await db.scalars(
                    select(Ticket)
                    .where(due_clause(now))
                    .order_by(Ticket.sla_deadline)
                    .limit(SCAN_BATCH)
                    .with_for_update(of=Ticket, skip_locked=True)
                )
            )
            .unique()
            .all()
        )
        for t in due:
            clock = clock_of(t)
            if clock is None:
                continue
            if t.sla_warned_at is None and clock.warning_due(now):
                t.sla_warned_at = now
                _log(db, t, "warning", ratio=round(clock.ratio(now), 3))
                counts["warning"] += 1
            if t.sla_breached_at is None and clock.breach_due(now):
                t.sla_breached_at = now
                t.sla_status = "breached"
                _log(db, t, "breached", overdue_seconds=round(-clock.remaining(now)))
                counts["breached"] += 1
        await db.commit()
    if counts["warning"] or counts["breached"]:
        log.info("SLA scan: %(warning)d warnings, %(breached)d breaches", counts)
        await bus.after_commit()
    return counts


async def scan_forever(stop: Any) -> None:
    """The SLA worker's scanner loop."""
    import asyncio

    interval = get_settings().sla_scan_seconds
    log.info("SLA scanner every %.1fs (speed-up x%g)", interval, get_settings().sla_speedup)
    while not stop.is_set():
        try:
            await scan_once()
        except Exception:
            log.exception("SLA scan failed; retrying")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass


# ------------------------------------------------------------------------------------------------ history
async def score_history(db: AsyncSession) -> int:
    """Give resolved / closed tickets that never had a clock (imported history) their real outcome: the clock ran
    from created_at to the resolution, against the default policy of their priority. Idempotent (only rows with no
    SLA yet). Used by the dataset importer and the history backfill; migration 0009 did the same for existing data."""
    from sqlalchemy import text

    result = await db.execute(
        text(
            """
            UPDATE tickets t SET
                sla_policy_id = p.id,
                sla_target_seconds = p.target_minutes * 60,
                sla_started_at = t.created_at,
                sla_deadline = t.created_at + make_interval(mins => p.target_minutes),
                sla_stopped_at = coalesce(t.resolved_at, t.closed_at),
                sla_status = CASE WHEN coalesce(t.resolved_at, t.closed_at)
                                       <= t.created_at + make_interval(mins => p.target_minutes)
                                  THEN 'met' ELSE 'breached' END,
                sla_breached_at = CASE WHEN coalesce(t.resolved_at, t.closed_at)
                                            > t.created_at + make_interval(mins => p.target_minutes)
                                       THEN t.created_at + make_interval(mins => p.target_minutes) END
            FROM sla_policies p
            WHERE p.priority = t.priority AND p.category IS NULL AND p.is_active
              AND t.sla_started_at IS NULL AND t.status IN ('RESOLVED', 'CLOSED')
              AND coalesce(t.resolved_at, t.closed_at) IS NOT NULL
            """
        )
    )
    return result.rowcount or 0
