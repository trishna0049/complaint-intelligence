"""Tickets: create (AI triage runs automatically), queue, details workspace, lifecycle actions, comments, files.

Agents only ever see their own, their team's and their created tickets (enforced in services.tickets).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.core.db import get_session
from app.domain.lifecycle import Status
from app.models import Ticket, User
from app.schemas.common import Page
from app.schemas.knowledge import SimilarTicketOut
from app.schemas.tickets import (
    AnalysisOut,
    AssignRequest,
    AttachmentOut,
    CommentCreate,
    CommentOut,
    EventOut,
    PreviousTicket,
    ReasonRequest,
    ResolveRequest,
    TicketCreate,
    TicketDetail,
    TicketListItem,
    TicketUpdate,
    sla_view,
)
from app.services import retrieval, storage
from app.services import tickets as svc
from app.services.knowledge import snippet

router = APIRouter(prefix="/tickets", tags=["tickets"])
Db = Depends(get_session)


async def to_detail(db: AsyncSession, user: User, t: Ticket) -> TicketDetail:
    bundle = await svc.detail_bundle(db, user, t)
    detail = TicketDetail.model_validate(t)
    detail.sla = sla_view(t)
    detail.copilot = AnalysisOut.model_validate(bundle["copilot"]) if bundle["copilot"] else None
    detail.comments = [CommentOut.model_validate(c) for c in bundle["comments"]]
    detail.attachments = [AttachmentOut.model_validate(a) for a in bundle["attachments"]]
    detail.timeline = [EventOut.model_validate(e) for e in bundle["timeline"]]
    detail.previous_tickets = [PreviousTicket.model_validate(p) for p in bundle["previous_tickets"]]
    detail.allowed_actions = bundle["allowed_actions"]
    detail.can_view = svc.can_view(user, t)
    detail.pipeline = bundle["pipeline"]
    return detail


def _statuses(value: str | None) -> list[str] | None:
    if not value:
        return None
    if value == "open":
        return svc.OPEN_STATUS_VALUES
    out = [s.strip().upper() for s in value.split(",") if s.strip()]
    valid = {s.value for s in Status}
    return [s for s in out if s in valid] or ["__none__"]


def _filters(
    q: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, description="Comma-separated states, or 'open'"),
    category: str | None = None,
    sentiment: str | None = None,
    priority: str | None = None,
    channel: str | None = None,
    source: str | None = Query(default=None, pattern="^(dataset|new)$"),
    needs_review: bool | None = None,
    assignee: str | None = Query(default=None, pattern=r"^(me|none|\d+)$"),
    team_id: int | None = None,
    escalated: bool | None = None,
    sla: str | None = Query(default=None, pattern="^(at_risk|breached|paused|running)$"),
) -> dict[str, Any]:
    return {
        "q": q,
        "status": _statuses(status),
        "category": category,
        "sentiment": sentiment,
        "priority": priority,
        "channel": channel,
        "source": source,
        "needs_review": needs_review,
        "assignee": assignee,
        "team_id": team_id,
        "escalated": escalated,
        "sla": sla,
    }


@router.post("", response_model=TicketDetail, status_code=status.HTTP_201_CREATED)
async def create_ticket(body: TicketCreate, user: CurrentUser, db: AsyncSession = Db) -> TicketDetail:
    return await to_detail(db, user, await svc.create_ticket(db, user, body))


@router.get("", response_model=Page[TicketListItem])
async def list_tickets(
    user: CurrentUser,
    db: AsyncSession = Db,
    filters: dict[str, Any] = Depends(_filters),
    sort: str = Query(default="newest", pattern="^(newest|oldest|priority|updated|sla)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> Page[TicketListItem]:
    items, total = await svc.list_tickets(db, user, sort=sort, page=page, page_size=page_size, **filters)
    rows = [TicketListItem.model_validate(t).model_copy(update={"sla": sla_view(t)}) for t in items]
    return Page(items=rows, total=total, page=page, page_size=page_size)


@router.get("/summary")
async def ticket_summary(
    user: CurrentUser, db: AsyncSession = Db, filters: dict[str, Any] = Depends(_filters)
) -> dict[str, Any]:
    """Ticket counts per state within what the caller can see (queue tabs, My Work)."""
    filters.pop("status", None)
    counts = await svc.status_counts(db, user, **filters)
    return {
        "by_status": {s.value: counts.get(s.value, 0) for s in Status},
        "open": sum(counts.get(s, 0) for s in svc.OPEN_STATUS_VALUES),
    }


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: int, user: CurrentUser, db: AsyncSession = Db) -> TicketDetail:
    return await to_detail(db, user, await svc.get_ticket(db, user, ticket_id))


@router.patch("/{ticket_id}", response_model=TicketDetail)
async def update_ticket(ticket_id: int, body: TicketUpdate, user: CurrentUser, db: AsyncSession = Db) -> TicketDetail:
    """Change the working status (IN_PROGRESS / WAITING_CUSTOMER) or correct the category."""
    return await to_detail(db, user, await svc.update_ticket(db, user, ticket_id, body))


@router.post("/{ticket_id}/assign", response_model=TicketDetail)
async def assign(ticket_id: int, body: AssignRequest, user: CurrentUser, db: AsyncSession = Db) -> TicketDetail:
    return await to_detail(db, user, await svc.assign(db, user, ticket_id, body.assignee_id, body.note))


@router.post("/{ticket_id}/auto-assign", response_model=TicketDetail)
async def auto_assign(ticket_id: int, user: CurrentUser, db: AsyncSession = Db) -> TicketDetail:
    """Admin: re-run the routing rules on an unassigned ticket (category -> team -> least-busy agent)."""
    return await to_detail(db, user, await svc.auto_assign(db, user, ticket_id))


@router.post("/{ticket_id}/escalate", response_model=TicketDetail)
async def escalate(ticket_id: int, body: ReasonRequest, user: CurrentUser, db: AsyncSession = Db) -> TicketDetail:
    return await to_detail(db, user, await svc.escalate(db, user, ticket_id, body.reason))


@router.post("/{ticket_id}/resolve", response_model=TicketDetail)
async def resolve(ticket_id: int, body: ResolveRequest, user: CurrentUser, db: AsyncSession = Db) -> TicketDetail:
    return await to_detail(db, user, await svc.resolve(db, user, ticket_id, body.resolution))


@router.post("/{ticket_id}/close", response_model=TicketDetail)
async def close(ticket_id: int, user: CurrentUser, db: AsyncSession = Db) -> TicketDetail:
    return await to_detail(db, user, await svc.close(db, user, ticket_id))


@router.post("/{ticket_id}/reopen", response_model=TicketDetail)
async def reopen(ticket_id: int, body: ReasonRequest, user: CurrentUser, db: AsyncSession = Db) -> TicketDetail:
    return await to_detail(db, user, await svc.reopen(db, user, ticket_id, body.reason))


@router.get("/{ticket_id}/similar", response_model=list[SimilarTicketOut])
async def similar(
    ticket_id: int, user: CurrentUser, db: AsyncSession = Db, limit: int = Query(default=5, ge=1, le=20)
) -> list[SimilarTicketOut]:
    """Past tickets like this one (hybrid: meaning + keywords), within what the caller may see."""
    t = await svc.get_ticket(db, user, ticket_id)
    return [
        SimilarTicketOut(
            id=s.ticket.id,
            ticket_number=s.ticket.ticket_number,
            subject=s.ticket.subject,
            snippet=snippet(s.ticket.description, 180),
            status=s.ticket.status,
            category=s.ticket.category,
            intent=s.ticket.intent,
            priority=s.ticket.priority,
            resolution=s.ticket.resolution,
            csat_score=s.ticket.csat_score,
            source=s.ticket.source,
            created_at=s.ticket.created_at,
            score=round(s.hit.score, 5),
            similarity=s.hit.similarity,
            matched_by=s.hit.matched_by,
        )
        for s in await retrieval.similar_tickets(db, user, t, limit=limit)
    ]


@router.get("/{ticket_id}/comments", response_model=list[CommentOut])
async def list_comments(ticket_id: int, user: CurrentUser, db: AsyncSession = Db) -> list[CommentOut]:
    t = await svc.get_ticket(db, user, ticket_id)
    return [CommentOut.model_validate(c) for c in (await svc.detail_bundle(db, user, t))["comments"]]


@router.post("/{ticket_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(ticket_id: int, body: CommentCreate, user: CurrentUser, db: AsyncSession = Db) -> CommentOut:
    return CommentOut.model_validate(await svc.add_comment(db, user, ticket_id, body.body))


@router.get("/{ticket_id}/timeline", response_model=list[EventOut])
async def timeline(ticket_id: int, user: CurrentUser, db: AsyncSession = Db) -> list[EventOut]:
    t = await svc.get_ticket(db, user, ticket_id)
    return [EventOut.model_validate(e) for e in (await svc.detail_bundle(db, user, t))["timeline"]]


@router.post("/{ticket_id}/attachments", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    ticket_id: int, user: CurrentUser, file: UploadFile = File(...), db: AsyncSession = Db
) -> AttachmentOut:
    return AttachmentOut.model_validate(await svc.add_attachment(db, user, ticket_id, file))


@router.get("/{ticket_id}/attachments/{attachment_id}")
async def download_attachment(
    ticket_id: int, attachment_id: int, user: CurrentUser, db: AsyncSession = Db
) -> FileResponse:
    att = await svc.get_attachment(db, user, ticket_id, attachment_id)
    return FileResponse(
        storage.path_for(att.storage_key),
        media_type=att.content_type,
        filename=att.filename,  # sent as Content-Disposition: attachment (never rendered inline)
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )
