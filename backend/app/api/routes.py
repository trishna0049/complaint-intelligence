from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.classifier import get_classifier
from app.ai.priority import BASE_PRIORITY
from app.core.config import get_settings
from app.core.db import get_session
from app.schemas import (
    ComplaintCreate,
    ComplaintDetail,
    ComplaintListItem,
    ComplaintUpdate,
    InsightOut,
    Page,
    TriagePreview,
)
from app.services import complaints as svc
from app.services.dashboard import cached_dashboard

router = APIRouter(prefix="/api")


def to_detail(c: Any) -> ComplaintDetail:
    detail = ComplaintDetail.model_validate(c)
    detail.insight = InsightOut.model_validate(c.insights[0]) if c.insights else None
    return detail


@router.get("/health")
def health() -> dict[str, Any]:
    s = get_settings()
    clf = get_classifier()
    return {
        "status": "ok",
        "classifier": clf.version if clf else None,
        "sentiment_model": s.sentiment_model if s.enable_transformers else "lexicon-fallback",
        "llm_provider": "openai" if s.llm_provider == "openai" and s.openai_api_key else "mock",
    }


@router.get("/categories")
def categories() -> list[dict[str, str]]:
    return [{"name": n, "base_priority": p} for n, p in BASE_PRIORITY.items()]


@router.post("/triage", response_model=TriagePreview)
async def triage_preview(body: ComplaintCreate) -> TriagePreview:
    """Run the NLP pipeline without saving anything (used by the 'Analyze' button)."""
    r = await svc.run_triage(body)
    return TriagePreview(**r.__dict__)


@router.post("/complaints", response_model=ComplaintDetail, status_code=201)
async def create_complaint(body: ComplaintCreate, db: AsyncSession = Depends(get_session)) -> ComplaintDetail:
    return to_detail(await svc.create_complaint(db, body))


@router.get("/complaints", response_model=Page[ComplaintListItem])
async def list_complaints(
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
) -> Page[ComplaintListItem]:
    items, total = await svc.list_complaints(
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
    return Page(items=[ComplaintListItem.model_validate(c) for c in items], total=total, page=page, page_size=page_size)


@router.get("/complaints/{complaint_id}", response_model=ComplaintDetail)
async def get_complaint(complaint_id: int, db: AsyncSession = Depends(get_session)) -> ComplaintDetail:
    return to_detail(await svc.get_complaint(db, complaint_id))


@router.patch("/complaints/{complaint_id}", response_model=ComplaintDetail)
async def update_complaint(
    complaint_id: int, body: ComplaintUpdate, db: AsyncSession = Depends(get_session)
) -> ComplaintDetail:
    return to_detail(await svc.update_complaint(db, complaint_id, body))


@router.post("/complaints/{complaint_id}/insights", response_model=InsightOut, status_code=201)
async def generate_insights(complaint_id: int, db: AsyncSession = Depends(get_session)) -> InsightOut:
    """Summarise the complaint, extract key issues and recommend actions with the LLM."""
    return InsightOut.model_validate(await svc.create_insight(db, complaint_id))


@router.get("/dashboard")
async def get_dashboard(
    days: int = Query(default=30, ge=7, le=365), db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await cached_dashboard(db, days)
