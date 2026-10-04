"""Tickets: create (AI triage runs automatically), search, read, update."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Ticket
from app.schemas.common import Page
from app.schemas.tickets import AnalysisOut, TicketCreate, TicketDetail, TicketListItem, TicketUpdate
from app.services import tickets as svc

router = APIRouter(prefix="/tickets", tags=["tickets"])


def to_detail(t: Ticket) -> TicketDetail:
    detail = TicketDetail.model_validate(t)
    copilot = svc.latest_copilot(t)
    detail.copilot = AnalysisOut.model_validate(copilot) if copilot else None
    return detail


@router.post("", response_model=TicketDetail, status_code=201)
async def create_ticket(body: TicketCreate, db: AsyncSession = Depends(get_session)) -> TicketDetail:
    return to_detail(await svc.create_ticket(db, body))


@router.get("", response_model=Page[TicketListItem])
async def list_tickets(
    db: AsyncSession = Depends(get_session),
    q: str | None = Query(default=None, max_length=200),
    status: str | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    priority: str | None = None,
    channel: str | None = None,
    source: str | None = Query(default=None, pattern="^(dataset|new)$"),
    needs_review: bool | None = None,
    sort: str = Query(default="newest", pattern="^(newest|oldest|priority)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> Page[TicketListItem]:
    items, total = await svc.list_tickets(
        db,
        q=q,
        status=status,
        category=category,
        sentiment=sentiment,
        priority=priority,
        channel=channel,
        source=source,
        needs_review=needs_review,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return Page(items=[TicketListItem.model_validate(t) for t in items], total=total, page=page, page_size=page_size)


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: int, db: AsyncSession = Depends(get_session)) -> TicketDetail:
    return to_detail(await svc.get_ticket(db, ticket_id))


@router.patch("/{ticket_id}", response_model=TicketDetail)
async def update_ticket(ticket_id: int, body: TicketUpdate, db: AsyncSession = Depends(get_session)) -> TicketDetail:
    return to_detail(await svc.update_ticket(db, ticket_id, body))
