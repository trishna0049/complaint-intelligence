from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.lifecycle import Status
from app.schemas.auth import TeamRef

Channel = Literal["Web", "Email", "Inbound", "Outcall"]


class TicketCreate(BaseModel):
    subject: str | None = Field(default=None, max_length=255)
    description: str = Field(min_length=5, max_length=10_000)
    channel: Channel = "Web"
    customer_code: str | None = Field(default=None, max_length=16, description="Link to an existing customer")
    customer_name: str | None = Field(default=None, max_length=160)
    order_id: str | None = Field(default=None, max_length=64)
    product: str | None = Field(default=None, max_length=120)
    amount_inr: float | None = Field(default=None, ge=0, le=100_000_000)
    city: str | None = Field(default=None, max_length=120)

    @field_validator("description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if len(v.strip()) < 5:
            raise ValueError("Describe the complaint (at least 5 characters)")
        return v.strip()


class TicketUpdate(BaseModel):
    """PATCH: change the working status (start / wait on customer / resume) or correct the category."""

    status: Literal["IN_PROGRESS", "WAITING_CUSTOMER"] | None = None
    category: str | None = Field(default=None, max_length=64)  # human correction


class AssignRequest(BaseModel):
    assignee_id: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=1000)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        if len(v.strip()) < 3:
            raise ValueError("Give a reason (at least 3 characters)")
        return v.strip()


class ResolveRequest(BaseModel):
    resolution: str = Field(min_length=3, max_length=5000, description="What was done for the customer")

    @field_validator("resolution")
    @classmethod
    def _strip(cls, v: str) -> str:
        if len(v.strip()) < 3:
            raise ValueError("Describe the resolution (at least 3 characters)")
        return v.strip()


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Write a comment")
        return v.strip()


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TicketListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_number: str
    subject: str
    channel: str
    status: Status
    category: str | None
    intent: str | None
    sentiment: str | None
    priority: str
    category_confidence: float | None
    needs_review: bool
    source: str
    description_source: str
    customer_name: str | None
    city: str | None
    assignee: UserRef | None
    team: TeamRef | None
    escalated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # The classifier's top categories from the latest triage run, e.g. [["Refund Related", 0.41], ...].
    top_categories: list[tuple[str, float]] = []


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    category: str | None
    intent: str | None
    sentiment: str | None
    priority: str | None
    confidence: float | None
    summary: str | None
    root_cause: str | None = None
    key_issues: list[str] | None
    recommendations: list[str] | None
    draft_response: str | None
    provider: str | None
    model: str | None
    model_version: str | None
    prompt_version: str | None
    alternatives: list[tuple[str, float]] | None = None
    # RAG references given to the copilot (help articles A1.., similar tickets T1..) and whether each was cited.
    grounding: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None
    # Human review of the draft (copilot runs): pending | accepted | discarded | superseded
    draft_status: str | None = None
    reviewed_by: UserRef | None = None
    reviewed_at: datetime | None = None
    final_response: str | None = None
    edited: bool | None = None
    comment_id: int | None = None
    discard_reason: str | None = None
    created_at: datetime


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    body: str
    ai_assisted: bool
    author: UserRef | None
    created_at: datetime


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: UserRef | None
    created_at: datetime


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    actor: UserRef | None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_code: str
    name: str
    segment: str
    region: str | None
    created_at: datetime


class PreviousTicket(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_number: str
    subject: str
    status: Status
    category: str | None
    created_at: datetime


class TicketDetail(TicketListItem):
    description: str
    order_id: str | None
    product: str | None
    amount_inr: float | None
    csat_score: int | None
    resolution: str | None
    reopen_count: int
    first_response_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    intent_confidence: float | None
    sentiment_score: float | None
    priority_reasons: list[dict[str, Any]] | None
    entities: dict[str, Any] | None
    labels_from: str
    model_version: str | None
    customer: CustomerOut | None
    # Latest copilot output (summary, key issues, recommendations, draft response), if any.
    copilot: AnalysisOut | None = None
    comments: list[CommentOut] = []
    attachments: list[AttachmentOut] = []
    timeline: list[EventOut] = []
    previous_tickets: list[PreviousTicket] = []
    # Lifecycle actions the current user may perform now (state machine + permissions) — the UI shows only these.
    allowed_actions: list[str] = []
    # False only in the response to a change that moved the ticket out of the caller's scope (e.g. a category fix
    # routed it to another team); the next GET returns 404.
    can_view: bool = True
