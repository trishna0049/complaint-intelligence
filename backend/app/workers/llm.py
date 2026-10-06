"""LLM worker.

* ai.analysis.completed -> draft the copilot answer (summary, root cause, next steps, draft reply, grounded in help
  articles and similar tickets) so it is ready when the agent opens the ticket. Off with COPILOT_AUTO=false.
  The draft is only a proposal: nothing reaches the customer until an agent accepts it.

LLM failures (rate limits, timeouts) are retried and then dead-lettered like any other handler error, so an Admin
can replay them once the provider is back.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events.consumer import Consumer
from app.events.envelope import Envelope, EventType
from app.services import copilot


async def on_analysis_completed(db: AsyncSession, env: Envelope) -> None:
    if env.ticket_id is not None and get_settings().copilot_auto:
        await copilot.auto_draft(db, env.ticket_id)


CONSUMER = Consumer(
    name="llm-worker",
    description="Copilot drafts after triage",
    handlers={EventType.AI_ANALYSIS_COMPLETED: on_analysis_completed},
)
