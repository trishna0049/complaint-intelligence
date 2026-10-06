from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Priority = Literal["Low", "Medium", "High", "Critical"]
SlaState = Literal["none", "running", "at_risk", "paused", "breached", "met"]


class SlaPolicyIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    priority: Priority
    category: str | None = Field(default=None, max_length=64, description="Empty = every category")
    target_minutes: int = Field(ge=1, le=60 * 24 * 60)  # up to 60 days
    is_active: bool = True


class SlaPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    target_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 60)
    is_active: bool | None = None


class SlaPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    priority: Priority
    category: str | None
    target_minutes: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SlaPolicyRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    target_minutes: int


class SlaView(BaseModel):
    """The ticket's SLA as the UI shows it (the countdown is computed client-side from `deadline`)."""

    state: SlaState
    deadline: datetime | None
    remaining_seconds: int | None
    ratio: float | None  # share of the target used
    target_seconds: int | None
    paused: bool
    started_at: datetime | None
    breached_at: datetime | None
    warned_at: datetime | None
    policy: SlaPolicyRef | None = None
