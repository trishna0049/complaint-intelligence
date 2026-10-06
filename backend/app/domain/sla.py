"""SLA maths — pure functions, unit-tested (spec: "SLA math (including the pause rule)").

A ticket's clock has a start, a target and the time spent paused. The spec's pause rule: the clock stops while the
ticket is WAITING_CUSTOMER, so the deadline moves out by exactly the time spent waiting.

    elapsed  = (now or stop) - started - paused            (seconds that count against the SLA)
    deadline = started + target + paused                    (+ the running pause, if paused now)
    warning at 80 % of the target, breach at 100 % — each fired once (the engine records when).

States shown to people: running (< 80 %), at_risk (≥ 80 %), breached, paused, met (resolved in time), none.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

WARNING_RATIO = 0.8


class SlaState(StrEnum):
    NONE = "none"  # no clock (not triaged yet, or no policy)
    RUNNING = "running"
    AT_RISK = "at_risk"  # 80 % or more used
    PAUSED = "paused"  # waiting on the customer
    BREACHED = "breached"  # 100 % used (stays breached after resolution)
    MET = "met"  # resolved before the deadline


@dataclass(frozen=True)
class Clock:
    started_at: datetime
    target_seconds: int
    paused_seconds: int = 0  # completed pauses
    paused_since: datetime | None = None  # a pause in progress
    stopped_at: datetime | None = None  # resolved (the clock no longer runs)
    breached_at: datetime | None = None

    def _paused_total(self, now: datetime) -> float:
        running_pause = (now - self.paused_since).total_seconds() if self.paused_since else 0.0
        return self.paused_seconds + max(0.0, running_pause)

    def elapsed(self, now: datetime) -> float:
        end = self.stopped_at or now
        return max(0.0, (end - self.started_at).total_seconds() - self._paused_total(end))

    def deadline(self, now: datetime) -> datetime:
        return self.started_at + timedelta(seconds=self.target_seconds + self._paused_total(self.stopped_at or now))

    def remaining(self, now: datetime) -> float:
        return self.target_seconds - self.elapsed(now)

    def ratio(self, now: datetime) -> float:
        return self.elapsed(now) / self.target_seconds if self.target_seconds else 1.0

    def warning_due(self, now: datetime) -> bool:
        return self.paused_since is None and self.stopped_at is None and self.ratio(now) >= WARNING_RATIO

    def breach_due(self, now: datetime) -> bool:
        return self.paused_since is None and self.stopped_at is None and self.ratio(now) >= 1.0

    def state(self, now: datetime) -> SlaState:
        if self.breached_at is not None or (
            self.stopped_at is None and self.paused_since is None and self.ratio(now) >= 1
        ):
            return SlaState.BREACHED
        if self.stopped_at is not None:
            return SlaState.MET if self.elapsed(now) <= self.target_seconds else SlaState.BREACHED
        if self.paused_since is not None:
            return SlaState.PAUSED
        return SlaState.AT_RISK if self.ratio(now) >= WARNING_RATIO else SlaState.RUNNING


def pause(clock: Clock, now: datetime) -> Clock:
    if clock.paused_since is not None or clock.stopped_at is not None:
        return clock
    return Clock(clock.started_at, clock.target_seconds, clock.paused_seconds, now, None, clock.breached_at)


def resume(clock: Clock, now: datetime) -> Clock:
    """End a pause (or, after a reopen, the time the ticket spent resolved) — that time never counts."""
    if clock.stopped_at is not None:  # reopened: the resolved interval is treated as paused
        extra = (now - clock.stopped_at).total_seconds()
        return Clock(
            clock.started_at, clock.target_seconds, clock.paused_seconds + int(extra), None, None, clock.breached_at
        )
    if clock.paused_since is None:
        return clock
    extra = (now - clock.paused_since).total_seconds()
    return Clock(
        clock.started_at, clock.target_seconds, clock.paused_seconds + int(extra), None, None, clock.breached_at
    )


def stop(clock: Clock, now: datetime) -> Clock:
    if clock.stopped_at is not None:
        return clock
    resumed = resume(clock, now) if clock.paused_since is not None else clock
    return Clock(resumed.started_at, resumed.target_seconds, resumed.paused_seconds, None, now, resumed.breached_at)


def retarget(clock: Clock, target_seconds: int) -> Clock:
    """A new priority / category (new policy) keeps the start and the pauses, only the target changes."""
    return Clock(
        clock.started_at, target_seconds, clock.paused_seconds, clock.paused_since, clock.stopped_at, clock.breached_at
    )


def target_seconds(target_minutes: int, speedup: float) -> int:
    """Demo speed-up: SLA_SPEEDUP=60 turns a 2-hour SLA into 2 minutes of real time (1 for real use)."""
    return max(1, round(target_minutes * 60 / max(speedup, 1e-6)))
