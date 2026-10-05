"""AI endpoints: triage preview, the copilot (generate / regenerate) and the human review of its draft reply."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.tickets import to_detail
from app.auth.dependencies import CurrentUser
from app.core.db import get_session
from app.schemas.ai import AcceptDraftRequest, AnalyzeRequest, DiscardDraftRequest, DraftResponseRequest, TriagePreview
from app.schemas.tickets import AnalysisOut, TicketDetail
from app.services import copilot
from app.services import tickets as svc

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/analyze", response_model=TriagePreview)
async def analyze(body: AnalyzeRequest, user: CurrentUser) -> TriagePreview:
    """Run the NLP triage pipeline on a text without saving anything (the 'Analyze' button)."""
    r = await svc.run_triage(body)
    return TriagePreview(**r.__dict__)


@router.post("/draft-response", response_model=AnalysisOut, status_code=201)
async def draft_response(
    body: DraftResponseRequest, user: CurrentUser, db: AsyncSession = Depends(get_session)
) -> AnalysisOut:
    """Copilot: summary, likely root cause, key issues, next steps and a draft reply (PII masked first). Running it
    again regenerates: the previous pending draft is marked superseded. Nothing is sent to the customer."""
    return AnalysisOut.model_validate(await copilot.generate(db, user, body.ticket_id))


@router.post("/drafts/{analysis_id}/accept", response_model=TicketDetail)
async def accept_draft(
    analysis_id: int, body: AcceptDraftRequest, user: CurrentUser, db: AsyncSession = Depends(get_session)
) -> TicketDetail:
    """The agent approves the draft (possibly edited); it is posted as their comment, marked AI-assisted."""
    return await to_detail(db, user, await copilot.accept(db, user, analysis_id, body.response))


@router.post("/drafts/{analysis_id}/discard", response_model=TicketDetail)
async def discard_draft(
    analysis_id: int, body: DiscardDraftRequest, user: CurrentUser, db: AsyncSession = Depends(get_session)
) -> TicketDetail:
    return await to_detail(db, user, await copilot.discard(db, user, analysis_id, body.reason))
