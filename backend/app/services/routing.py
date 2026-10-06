"""Routing service: gathers the facts, asks the pure rules in app.domain.routing, and applies the decision to the
ticket — in the caller's transaction, with a `routed` timeline event explaining which rule fired.

Runs right after triage on ticket creation, again when a person confirms or corrects the category of a ticket
nobody has started on, and when an Admin presses "Auto-assign" on a ticket waiting in a team queue.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.lifecycle import Action, Status, next_status
from app.domain.routing import Decision, Outcome, decide
from app.models import Ticket, User
from app.repositories import routing as repo
from app.repositories import users as users_repo
from app.services import timeline


def _now() -> datetime:
    return datetime.now(UTC)


async def decide_for(db: AsyncSession, t: Ticket) -> Decision:
    team = await repo.category_team(db, t.category)
    if team is not None and not t.needs_review:
        await repo.lock_team(db, team[0])
    return decide(
        category=t.category,
        needs_review=t.needs_review,
        confidence=t.category_confidence,
        team_id=team[0] if team else None,
        team_name=team[1] if team else None,
        candidates=await repo.candidates(db, team[0]) if team and not t.needs_review else [],
        max_open=get_settings().routing_max_open_per_agent,
    )


def _move(db: AsyncSession, t: Ticket, action: Action, actor: User | None, trigger: str) -> None:
    new = next_status(t.status, action, has_assignee=t.assignee_id is not None)
    if new.value == t.status:
        return
    old, t.status = t.status, new.value
    timeline.record(
        db, t, "status_changed", actor, **{"from": old, "to": new.value, "action": action.value, "trigger": trigger}
    )


async def route(db: AsyncSession, t: Ticket, *, actor: User | None = None, trigger: str = "triage") -> Decision:
    """Route `t` (row already locked or freshly created) and record the decision. The caller commits."""
    d = await decide_for(db, t)
    previous = {"assignee_id": t.assignee_id, "team_id": t.team_id}
    # The decision first, then the moves it causes (the timeline reads in that order).
    timeline.record(
        db,
        t,
        "routed",
        actor,
        **{
            "outcome": d.outcome.value,
            "rule": d.rule.value,
            "reason": d.reason,
            "trigger": trigger,
            "team_id": d.team_id,
            "team": d.team_name,
            "assignee_id": d.assignee_id,
            "assignee": d.assignee.name if d.assignee else None,
            "open_tickets": d.assignee.open_tickets if d.assignee else None,
            "candidates": d.candidates,
            "available": d.available,
            "previous_assignee_id": previous["assignee_id"],
            "previous_team_id": previous["team_id"],
        },
    )
    if d.outcome is Outcome.ASSIGNED:
        assert d.assignee is not None
        t.assignee_id, t.team_id = d.assignee.id, d.team_id
        _move(db, t, Action.ASSIGN, actor, trigger)
        await repo.mark_assigned(db, d.assignee.id, _now())
    elif d.outcome is Outcome.TEAM_QUEUE:
        t.team_id = d.team_id
        if t.assignee_id is not None and t.status == Status.ASSIGNED:
            t.assignee_id = None
            _move(db, t, Action.RELEASE, actor, trigger)
    elif d.outcome is Outcome.UNROUTED and t.status == Status.ASSIGNED:
        t.team_id = t.assignee_id = None
        _move(db, t, Action.RELEASE, actor, trigger)
    t.updated_at = _now()
    moved_from_owner = previous["assignee_id"] is not None and previous["assignee_id"] != t.assignee_id
    if moved_from_owner or previous["team_id"] not in (None, t.team_id):
        users_repo.audit(
            db,
            "ticket.reroute",
            actor_id=actor.id if actor else None,
            resource_type="ticket",
            resource_id=t.id,
            metadata={
                "ticket": t.ticket_number,
                "trigger": trigger,
                "rule": d.rule.value,
                "from_user": previous["assignee_id"],
                "to_user": t.assignee_id,
                "from_team": previous["team_id"],
                "to_team": t.team_id,
            },
        )
    return d


async def reroute_after_category_change(db: AsyncSession, t: Ticket, *, actor: User, trigger: str) -> Decision | None:
    """A confirmed / corrected category re-routes the ticket only while nobody has started on it: TRIAGED and
    unassigned, or ASSIGNED to someone outside the category's team. Tickets in progress keep their owner."""
    if t.needs_review:
        return None
    if t.status == Status.TRIAGED and t.assignee_id is None:
        return await route(db, t, actor=actor, trigger=trigger)
    if t.status == Status.ASSIGNED:
        team = await repo.category_team(db, t.category)
        if (team[0] if team else None) != t.team_id:
            return await route(db, t, actor=actor, trigger=trigger)
    return None
