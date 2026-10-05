"""Routing rules — deterministic, never the LLM (spec: "Priority, SLA and routing use rules").

    category ──► owning team (categories.team_id, editable by Admins) ──► least-busy active agent of that team

The rules are checked in order and the first that applies decides:

    REVIEW      the category confidence is below REVIEW_THRESHOLD → nobody is assigned; the ticket waits in the
                low-confidence review queue until a person confirms or corrects the category (then it is routed)
    NO_TEAM     no team owns the category → left unrouted for an Admin
    NO_AGENTS   the team has no active agents → team queue (team set, no assignee)
    AT_CAPACITY every agent already has `max_open` or more open tickets → team queue
    LEAST_BUSY  the active agent with the fewest open tickets; ties go to whoever was assigned least recently
                (never-assigned first), then the lowest user id — so equal loads are shared round-robin

This module is pure (no database): the routing service gathers the candidates and applies the decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Outcome(StrEnum):
    ASSIGNED = "assigned"  # team + agent chosen
    TEAM_QUEUE = "team_queue"  # team chosen, waiting for an agent
    REVIEW = "review"  # low confidence: waiting for a person to confirm the category
    UNROUTED = "unrouted"  # no team owns the category


class Rule(StrEnum):
    REVIEW = "REVIEW"
    NO_TEAM = "NO_TEAM"
    NO_AGENTS = "NO_AGENTS"
    AT_CAPACITY = "AT_CAPACITY"
    LEAST_BUSY = "LEAST_BUSY"


@dataclass(frozen=True)
class Candidate:
    id: int
    name: str
    open_tickets: int
    last_assigned_at: datetime | None = None


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    rule: Rule
    reason: str
    team_id: int | None = None
    team_name: str | None = None
    assignee: Candidate | None = None
    candidates: int = 0  # active agents considered
    available: int = 0  # of those, below capacity

    @property
    def assignee_id(self) -> int | None:
        return self.assignee.id if self.assignee else None


def _tie_break(c: Candidate) -> tuple[int, int, float, int]:
    never = c.last_assigned_at is None
    return (c.open_tickets, 0 if never else 1, 0.0 if never else c.last_assigned_at.timestamp(), c.id)


def least_busy(candidates: list[Candidate], max_open: int) -> Candidate | None:
    pool = [c for c in candidates if c.open_tickets < max_open]
    return min(pool, key=_tie_break) if pool else None


def decide(
    *,
    category: str | None,
    needs_review: bool,
    confidence: float | None,
    team_id: int | None,
    team_name: str | None,
    candidates: list[Candidate],
    max_open: int,
) -> Decision:
    if needs_review:
        pct = f"{confidence:.0%}" if confidence is not None else "unknown"
        return Decision(
            Outcome.REVIEW,
            Rule.REVIEW,
            f"Category confidence {pct} is below the review threshold — a person must confirm the category first.",
        )
    if team_id is None:
        return Decision(Outcome.UNROUTED, Rule.NO_TEAM, f"No team owns the category {category or '(none)'}.")
    if not candidates:
        return Decision(
            Outcome.TEAM_QUEUE,
            Rule.NO_AGENTS,
            f"{team_name} has no active agents.",
            team_id=team_id,
            team_name=team_name,
        )
    chosen = least_busy(candidates, max_open)
    available = sum(1 for c in candidates if c.open_tickets < max_open)
    if chosen is None:
        return Decision(
            Outcome.TEAM_QUEUE,
            Rule.AT_CAPACITY,
            f"All {len(candidates)} agents in {team_name} have {max_open}+ open tickets.",
            team_id=team_id,
            team_name=team_name,
            candidates=len(candidates),
        )
    return Decision(
        Outcome.ASSIGNED,
        Rule.LEAST_BUSY,
        f"Least busy of {available} available agents in {team_name} ({chosen.open_tickets} open).",
        team_id=team_id,
        team_name=team_name,
        assignee=chosen,
        candidates=len(candidates),
        available=available,
    )
