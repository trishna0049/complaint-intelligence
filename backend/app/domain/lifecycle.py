"""Ticket lifecycle — the ONLY place that defines ticket states and the moves between them.

    NEW → TRIAGED → ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED
                                    ⇅ wait / resume      ↑           │
                              WAITING_CUSTOMER           └─ reopen ──┘ (RESOLVED or CLOSED → IN_PROGRESS / TRIAGED)

    escalate: TRIAGED, ASSIGNED, IN_PROGRESS, WAITING_CUSTOMER → ESCALATED → start / assign / resolve
    assign (or reassign): any open state → ASSIGNED;   resolve: ASSIGNED, IN_PROGRESS, WAITING_CUSTOMER, ESCALATED

Every action names the states it may start from and the state it leads to. Anything else is rejected with
`InvalidTransition`, which the API turns into HTTP 409. Permissions (who may do it) are checked separately in the
ticket service; this module only answers "is this move legal from this state".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_CUSTOMER = "WAITING_CUSTOMER"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


OPEN_STATUSES = frozenset(
    {Status.NEW, Status.TRIAGED, Status.ASSIGNED, Status.IN_PROGRESS, Status.WAITING_CUSTOMER, Status.ESCALATED}
)
DONE_STATUSES = frozenset({Status.RESOLVED, Status.CLOSED})
# States in which the SLA clock is stopped (the spec's pause rule); the SLA engine reads this.
SLA_PAUSED_STATUSES = frozenset({Status.WAITING_CUSTOMER})


class Action(StrEnum):
    TRIAGE = "triage"  # system: AI triage finished
    ASSIGN = "assign"  # assign or reassign to an agent
    START = "start"  # agent starts working
    WAIT_CUSTOMER = "wait_customer"  # waiting for the customer's reply (SLA paused)
    RESUME = "resume"  # customer replied / work continues
    ESCALATE = "escalate"  # manual, or automatic on SLA breach
    RESOLVE = "resolve"
    CLOSE = "close"
    REOPEN = "reopen"


@dataclass(frozen=True)
class Transition:
    action: Action
    sources: frozenset[Status]
    target: Status | None  # None: decided by `reopen_target`
    label: str


_ASSIGNABLE = frozenset(
    {Status.NEW, Status.TRIAGED, Status.ASSIGNED, Status.IN_PROGRESS, Status.WAITING_CUSTOMER, Status.ESCALATED}
)

TRANSITIONS: dict[Action, Transition] = {
    t.action: t
    for t in (
        Transition(Action.TRIAGE, frozenset({Status.NEW}), Status.TRIAGED, "Triage complete"),
        Transition(Action.ASSIGN, _ASSIGNABLE, Status.ASSIGNED, "Assign"),
        Transition(Action.START, frozenset({Status.ASSIGNED, Status.ESCALATED}), Status.IN_PROGRESS, "Start work"),
        Transition(Action.WAIT_CUSTOMER, frozenset({Status.IN_PROGRESS}), Status.WAITING_CUSTOMER, "Wait on customer"),
        Transition(Action.RESUME, frozenset({Status.WAITING_CUSTOMER}), Status.IN_PROGRESS, "Customer replied"),
        Transition(
            Action.ESCALATE,
            frozenset({Status.TRIAGED, Status.ASSIGNED, Status.IN_PROGRESS, Status.WAITING_CUSTOMER}),
            Status.ESCALATED,
            "Escalate",
        ),
        Transition(
            Action.RESOLVE,
            frozenset({Status.ASSIGNED, Status.IN_PROGRESS, Status.WAITING_CUSTOMER, Status.ESCALATED}),
            Status.RESOLVED,
            "Resolve",
        ),
        Transition(Action.CLOSE, frozenset({Status.RESOLVED}), Status.CLOSED, "Close"),
        Transition(Action.REOPEN, frozenset({Status.RESOLVED, Status.CLOSED}), None, "Reopen"),
    )
}


class InvalidTransition(Exception):
    def __init__(self, action: Action, current: Status) -> None:
        allowed = ", ".join(sorted(TRANSITIONS[action].sources))
        super().__init__(
            f"Can't {action.value.replace('_', ' ')} a ticket that is {current.value} (allowed from: {allowed})."
        )
        self.action = action
        self.current = current


def reopen_target(has_assignee: bool) -> Status:
    """A reopened ticket goes straight back to its agent, or to the triaged pool if nobody owns it."""
    return Status.IN_PROGRESS if has_assignee else Status.TRIAGED


def next_status(current: Status | str, action: Action | str, *, has_assignee: bool = False) -> Status:
    """The state after `action`, or InvalidTransition."""
    current, action = Status(current), Action(action)
    t = TRANSITIONS[action]
    if current not in t.sources:
        raise InvalidTransition(action, current)
    return t.target if t.target is not None else reopen_target(has_assignee)


def allowed_actions(current: Status | str) -> list[Action]:
    """Every action that is legal from `current` (before permission checks)."""
    current = Status(current)
    return [a for a, t in TRANSITIONS.items() if current in t.sources and a is not Action.TRIAGE]


def is_open(status: Status | str) -> bool:
    return Status(status) in OPEN_STATUSES
