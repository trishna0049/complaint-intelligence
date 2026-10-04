"""AI endpoints: triage preview and the copilot's draft response."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.ai import AnalyzeRequest, DraftResponseRequest, TriagePreview
from app.schemas.tickets import AnalysisOut
from app.services import tickets as svc

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/analyze", response_model=TriagePreview)
async def analyze(body: AnalyzeRequest) -> TriagePreview:
    """Run the NLP triage pipeline on a text without saving anything (the 'Analyze' button)."""
    r = await svc.run_triage(body)
    return TriagePreview(**r.__dict__)


@router.post("/draft-response", response_model=AnalysisOut, status_code=201)
async def draft_response(body: DraftResponseRequest, db: AsyncSession = Depends(get_session)) -> AnalysisOut:
    """Copilot: LLM summary, key issues, recommended actions and a draft reply for a ticket (PII masked first)."""
    return AnalysisOut.model_validate(await svc.generate_copilot(db, body.ticket_id))
