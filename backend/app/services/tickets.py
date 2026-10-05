"""Ticket service: creation with AI triage, scoped reads, the lifecycle actions, comments and attachments.

Rules enforced here (the API layer only parses and serialises):
* Visibility — Admins see every ticket. Agents see tickets assigned to them, tickets of their team and tickets they
  created. Anything else is reported as 404, so ticket numbers of other teams don't leak.
* "Works on" — Agents may change a ticket assigned to them or owned by their team (a ticket they only created is
  read + comment).
* Spec permissions — reassigning outside one's own team and closing someone else's ticket are Admin only.
* Every state change goes through app.domain.lifecycle (illegal moves → 409), and is written to ticket_events —
  plus audit_logs for sensitive actions — in the same transaction as the change itself.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import ColumnElement, false, or_, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import PROMPT_VERSION, generate_insight
from app.ai.priority import BASE_PRIORITY, decide_priority
from app.ai.triage import TriageResult, triage
from app.domain.lifecycle import (
    DONE_STATUSES,
    OPEN_STATUSES,
    TRANSITIONS,
    Action,
    InvalidTransition,
    Status,
    allowed_actions,
    next_status,
)
from app.models import AIAnalysis, Customer, Ticket, TicketAttachment, TicketComment, User
from app.repositories import tickets as repo
from app.repositories import users as users_repo
from app.schemas.tickets import TicketCreate, TicketUpdate
from app.services import storage
from app.services.analytics import invalidate_cache

# ------------------------------------------------------------------------------------------------ helpers
REGIONS = {
    "North": [
        "delhi",
        "new delhi",
        "noida",
        "gurgaon",
        "gurugram",
        "chandigarh",
        "jaipur",
        "lucknow",
        "kanpur",
        "ludhiana",
        "amritsar",
        "dehradun",
        "agra",
        "varanasi",
        "faridabad",
        "ghaziabad",
    ],
    "South": [
        "bangalore",
        "bengaluru",
        "chennai",
        "hyderabad",
        "kochi",
        "cochin",
        "coimbatore",
        "mysore",
        "mysuru",
        "madurai",
        "visakhapatnam",
        "vijayawada",
        "thiruvananthapuram",
        "mangalore",
    ],
    "West": ["mumbai", "pune", "ahmedabad", "surat", "vadodara", "nagpur", "nashik", "thane", "rajkot", "goa"],
    "East": ["kolkata", "bhubaneswar", "patna", "guwahati", "ranchi", "siliguri", "cuttack"],
    "Central": ["bhopal", "indore", "raipur", "jabalpur", "gwalior"],
}
_REGION_OF = {city: region for region, cities in REGIONS.items() for city in cities}


def region_for(city: str | None) -> str | None:
    return _REGION_OF.get((city or "").strip().lower())


def default_subject(text: str) -> str:
    first = text.strip().split("\n")[0]
    return first if len(first) <= 80 else first[:77].rstrip() + "…"


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(message: str, code: str = "invalid_transition") -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={"code": code, "message": message})


def _forbidden(message: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "forbidden", "message": message})


NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found")


# ------------------------------------------------------------------------------------------------ permissions
def visibility_clause(user: User) -> ColumnElement[bool]:
    if user.role == "ADMIN":
        return true()
    conditions = [Ticket.assignee_id == user.id, Ticket.created_by_id == user.id]
    if user.team_id is not None:
        conditions.append(Ticket.team_id == user.team_id)
    return or_(*conditions) if conditions else false()


def works_on(user: User, t: Ticket) -> bool:
    return user.role == "ADMIN" or t.assignee_id == user.id or (user.team_id is not None and t.team_id == user.team_id)


def permitted(user: User, t: Ticket, action: Action) -> bool:
    """Role / ownership check for an action (the state machine is checked separately)."""
    if user.role == "ADMIN":
        return True
    if action is Action.CLOSE:
        return t.assignee_id == user.id  # closing someone else's ticket is Admin only
    if action is Action.ASSIGN:
        # Agents may (re)assign within their own team only, including picking up an unrouted ticket.
        return user.team_id is not None and t.team_id in (None, user.team_id)
    return works_on(user, t)


def actions_for(user: User, t: Ticket) -> list[str]:
    return [a.value for a in allowed_actions(t.status) if permitted(user, t, a)]


def _transition(t: Ticket, action: Action) -> Status:
    try:
        return next_status(t.status, action, has_assignee=t.assignee_id is not None)
    except InvalidTransition as exc:
        raise _conflict(str(exc)) from exc


async def _load_for_change(db: AsyncSession, user: User, ticket_id: int, action: Action) -> Ticket:
    t = await repo.get(db, ticket_id, visible=visibility_clause(user), for_update=True)
    if t is None:
        raise NOT_FOUND
    if not permitted(user, t, action):
        what = {
            Action.CLOSE: "Only an Admin can close a ticket assigned to someone else.",
            Action.ASSIGN: "Only an Admin can reassign a ticket outside your own team.",
        }.get(action, "You can only change tickets assigned to you or your team.")
        raise _forbidden(what)
    return t


def _event(db: AsyncSession, t: Ticket, event_type: str, actor: User | None, **metadata: Any) -> None:
    repo.add_event(db, t.id, event_type, actor.id if actor else None, metadata)


def _status_change(db: AsyncSession, t: Ticket, new: Status, actor: User | None, action: Action, **meta: Any) -> None:
    old = t.status
    t.status = new.value
    t.updated_at = _now()
    _event(db, t, "status_changed", actor, **{"from": old, "to": new.value, "action": action.value, **meta})


async def _done(db: AsyncSession) -> None:
    await db.commit()
    await invalidate_cache()


# ------------------------------------------------------------------------------------------------ triage + create
async def run_triage(data: TicketCreate) -> TriageResult:
    # The models are CPU-bound; keep them off the event loop.
    return await asyncio.to_thread(
        triage,
        data.description,
        channel=data.channel,
        product=data.product,
        amount_inr=data.amount_inr,
        order_id=data.order_id,
    )


def apply_triage(t: Ticket, r: TriageResult) -> None:
    t.category, t.category_confidence = r.category, r.category_confidence
    t.intent, t.intent_confidence = r.intent, r.intent_confidence
    t.sentiment, t.sentiment_score = r.sentiment, r.sentiment_score
    t.priority, t.priority_reasons = r.priority, r.priority_reasons
    t.entities, t.needs_review = r.entities, r.needs_review
    t.model_version, t.labels_from = r.model_version, "model"


def triage_analysis(t: Ticket) -> AIAnalysis:
    """Record of one triage run (every AI output stores its confidence and model version)."""
    return AIAnalysis(
        ticket_id=t.id,
        kind="triage",
        category=t.category,
        intent=t.intent,
        sentiment=t.sentiment,
        priority=t.priority,
        entities=t.entities,
        confidence=t.category_confidence,
        model_version=t.model_version,
    )


async def _customer_for(db: AsyncSession, data: TicketCreate) -> Customer | None:
    if data.customer_code:
        customer = await repo.customer_by_code(db, data.customer_code)
        if customer is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown customer code")
        return customer
    if data.customer_name and data.customer_name.strip():
        return await repo.add_customer(
            db, Customer(name=data.customer_name.strip(), segment="Standard", region=region_for(data.city))
        )
    return None


async def create_ticket(db: AsyncSession, user: User, data: TicketCreate) -> Ticket:
    result = await run_triage(data)
    customer = await _customer_for(db, data)
    t = Ticket(
        source="new",
        subject=(data.subject or "").strip() or default_subject(data.description),
        description=data.description,
        description_source="customer",
        channel=data.channel,
        customer_id=customer.id if customer else None,
        customer_name=customer.name if customer else None,
        order_id=data.order_id or (result.entities["order_ids"][0] if result.entities["order_ids"] else None),
        product=data.product,
        amount_inr=data.amount_inr if data.amount_inr is not None else result.entities["max_amount_inr"],
        city=data.city,
        status=Status.NEW.value,
        created_by_id=user.id,
    )
    await repo.add(db, t)
    _event(db, t, "created", user, channel=t.channel)
    apply_triage(t, result)
    await repo.add_analysis(db, triage_analysis(t))
    t.status = next_status(t.status, Action.TRIAGE).value
    _event(
        db,
        t,
        "triaged",
        None,
        category=t.category,
        intent=t.intent,
        sentiment=t.sentiment,
        priority=t.priority,
        confidence=t.category_confidence,
        needs_review=t.needs_review,
        model_version=t.model_version,
    )
    await _done(db)
    return await get_ticket(db, user, t.id)


# ------------------------------------------------------------------------------------------------ reads
async def get_ticket(db: AsyncSession, user: User, ticket_id: int) -> Ticket:
    t = await repo.get(db, ticket_id, visible=visibility_clause(user))
    if t is None:
        raise NOT_FOUND
    return t


async def list_tickets(
    db: AsyncSession, user: User, *, assignee: str | None = None, **params: Any
) -> tuple[list[Ticket], int]:
    return await repo.search(db, visibility_clause(user), **_assignee_filter(user, assignee), **params)


async def status_counts(db: AsyncSession, user: User, *, assignee: str | None = None, **params: Any) -> dict[str, int]:
    return await repo.status_counts(db, visibility_clause(user), **_assignee_filter(user, assignee), **params)


def _assignee_filter(user: User, assignee: str | None) -> dict[str, Any]:
    if assignee == "me":
        return {"assignee_id": user.id}
    if assignee == "none":
        return {"unassigned": True}
    if assignee and assignee.isdigit():
        return {"assignee_id": int(assignee)}
    return {}


async def detail_bundle(db: AsyncSession, user: User, t: Ticket) -> dict[str, Any]:
    """Everything the Ticket Details workspace shows besides the ticket's own columns."""
    previous = await repo.previous_for_customer(db, t.customer_id, t.id) if t.customer_id else []
    timeline = await repo.events(db, t.id)
    return {
        "comments": await repo.comments(db, t.id),
        "attachments": await repo.attachments(db, t.id),
        "timeline": timeline or _historical_timeline(t),
        "previous_tickets": previous,
        "copilot": latest_copilot(t),
        "allowed_actions": actions_for(user, t),
    }


def _historical_timeline(t: Ticket) -> list[dict[str, Any]]:
    """Imported tickets have no event rows; show their real timestamps instead (marked as historical)."""
    if t.source != "dataset":
        return []
    items: list[dict[str, Any]] = [
        {
            "id": -1,
            "event_type": "created",
            "actor": None,
            "created_at": t.created_at,
            "metadata_": {"historical": True, "channel": t.channel},
        },
    ]
    if t.first_response_at:
        items.append(
            {
                "id": -2,
                "event_type": "first_response",
                "actor": t.assignee,
                "created_at": t.first_response_at,
                "metadata_": {"historical": True},
            }
        )
    if t.closed_at:
        items.append(
            {
                "id": -3,
                "event_type": "status_changed",
                "actor": t.assignee,
                "created_at": t.closed_at,
                "metadata_": {"historical": True, "from": "IN_PROGRESS", "to": "CLOSED", "csat": t.csat_score},
            }
        )
    return items


def latest_copilot(t: Ticket) -> AIAnalysis | None:
    return next((a for a in t.analyses if a.kind == "copilot"), None)


# ------------------------------------------------------------------------------------------------ lifecycle actions
async def assign(db: AsyncSession, user: User, ticket_id: int, assignee_id: int, note: str | None = None) -> Ticket:
    t = await _load_for_change(db, user, ticket_id, Action.ASSIGN)
    target = await repo.active_agent(db, assignee_id)
    if target is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown or inactive user")
    if user.role != "ADMIN" and target.team_id != user.team_id:
        raise _forbidden("Only an Admin can reassign a ticket outside your own team.")
    new_status = _transition(t, Action.ASSIGN)
    prev_assignee, prev_team = t.assignee_id, t.team_id
    if prev_assignee == target.id and t.status == new_status:
        raise _conflict(f"The ticket is already assigned to {target.name}.", "no_change")
    t.assignee_id = target.id
    if target.team_id is not None:
        t.team_id = target.team_id
    _event(
        db,
        t,
        "assigned",
        user,
        assignee_id=target.id,
        assignee=target.name,
        previous_assignee_id=prev_assignee,
        team_id=t.team_id,
        previous_team_id=prev_team,
        note=note,
    )
    if t.status != new_status:
        _status_change(db, t, new_status, user, Action.ASSIGN)
    if prev_assignee is not None or (prev_team is not None and prev_team != t.team_id):
        users_repo.audit(
            db,
            "ticket.reassign",
            actor_id=user.id,
            resource_type="ticket",
            resource_id=t.id,
            metadata={
                "ticket": t.ticket_number,
                "from_user": prev_assignee,
                "to_user": target.id,
                "from_team": prev_team,
                "to_team": t.team_id,
            },
        )
    await _done(db)
    return await get_ticket(db, user, t.id)


async def change_status(db: AsyncSession, user: User, ticket_id: int, target: str) -> Ticket:
    """PATCH status: start work, wait on the customer, or resume (customer replied)."""
    current = await get_ticket(db, user, ticket_id)
    action = next(
        (
            a
            for a in (Action.START, Action.RESUME, Action.WAIT_CUSTOMER)
            if TRANSITIONS[a].target == target and current.status in TRANSITIONS[a].sources
        ),
        None,
    )
    if action is None:
        raise _conflict(f"Can't move a ticket from {current.status} to {target}.")
    t = await _load_for_change(db, user, ticket_id, action)
    _status_change(db, t, _transition(t, action), user, action)
    await _done(db)
    return await get_ticket(db, user, t.id)


async def escalate(db: AsyncSession, user: User | None, ticket_id: int, reason: str, *, auto: bool = False) -> Ticket:
    """Manual escalation (agent / admin) or automatic (SLA breach, user=None)."""
    if user is None:
        t = await repo.get(db, ticket_id, for_update=True)
        if t is None:
            raise NOT_FOUND
    else:
        t = await _load_for_change(db, user, ticket_id, Action.ESCALATE)
    new_status = _transition(t, Action.ESCALATE)
    t.escalated_at = _now()
    _status_change(db, t, new_status, user, Action.ESCALATE, reason=reason, auto=auto)
    _event(db, t, "escalated", user, reason=reason, auto=auto)
    users_repo.audit(
        db,
        "ticket.escalate",
        actor_id=user.id if user else None,
        resource_type="ticket",
        resource_id=t.id,
        metadata={"ticket": t.ticket_number, "reason": reason, "auto": auto},
    )
    await _done(db)
    return t if user is None else await get_ticket(db, user, t.id)


async def resolve(db: AsyncSession, user: User, ticket_id: int, resolution: str) -> Ticket:
    t = await _load_for_change(db, user, ticket_id, Action.RESOLVE)
    new_status = _transition(t, Action.RESOLVE)
    t.resolution, t.resolved_at = resolution, _now()
    _status_change(db, t, new_status, user, Action.RESOLVE, resolution=resolution)
    await _done(db)
    return await get_ticket(db, user, t.id)


async def close(db: AsyncSession, user: User, ticket_id: int) -> Ticket:
    t = await _load_for_change(db, user, ticket_id, Action.CLOSE)
    new_status = _transition(t, Action.CLOSE)
    t.closed_at = _now()
    _status_change(db, t, new_status, user, Action.CLOSE)
    if t.assignee_id != user.id:
        users_repo.audit(
            db,
            "ticket.close_other",
            actor_id=user.id,
            resource_type="ticket",
            resource_id=t.id,
            metadata={"ticket": t.ticket_number, "assignee_id": t.assignee_id},
        )
    await _done(db)
    return await get_ticket(db, user, t.id)


async def reopen(db: AsyncSession, user: User, ticket_id: int, reason: str) -> Ticket:
    t = await _load_for_change(db, user, ticket_id, Action.REOPEN)
    new_status = _transition(t, Action.REOPEN)
    t.resolved_at = t.closed_at = None
    t.reopen_count += 1
    _status_change(db, t, new_status, user, Action.REOPEN, reason=reason)
    users_repo.audit(
        db,
        "ticket.reopen",
        actor_id=user.id,
        resource_type="ticket",
        resource_id=t.id,
        metadata={"ticket": t.ticket_number, "reason": reason, "reopen_count": t.reopen_count},
    )
    await _done(db)
    return await get_ticket(db, user, t.id)


async def update_ticket(db: AsyncSession, user: User, ticket_id: int, data: TicketUpdate) -> Ticket:
    if data.status:
        await change_status(db, user, ticket_id, data.status)
    if data.category:
        await correct_category(db, user, ticket_id, data.category)
    return await get_ticket(db, user, ticket_id)


async def correct_category(db: AsyncSession, user: User, ticket_id: int, category: str) -> Ticket:
    t = await get_ticket(db, user, ticket_id)
    if not works_on(user, t):
        raise _forbidden("You can only change tickets assigned to you or your team.")
    if Status(t.status) in DONE_STATUSES:
        raise _conflict("Reopen the ticket before changing its category.")
    if category == t.category:
        return t
    if category not in BASE_PRIORITY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown category")
    old_category, old_priority = t.category, t.priority
    t.category, t.category_confidence, t.needs_review, t.labels_from = category, 1.0, False, "human"
    decision = decide_priority(
        t.category, t.sentiment, t.amount_inr, bool((t.entities or {}).get("repeat_contact")), t.intent, t.description
    )
    t.priority = decision.priority
    t.priority_reasons = [
        {"rule": "BASE", "reason": f"Base priority for {t.category}", "from": "", "to": decision.base},
        *decision.reasons,
    ]
    t.updated_at = _now()
    _event(
        db,
        t,
        "category_corrected",
        user,
        **{"from": old_category, "to": category, "priority_from": old_priority, "priority_to": t.priority},
    )
    await _done(db)
    return t


# ------------------------------------------------------------------------------------------------ comments & files
async def add_comment(
    db: AsyncSession, user: User, ticket_id: int, body: str, *, ai_assisted: bool = False
) -> TicketComment:
    t = await get_ticket(db, user, ticket_id)
    comment = TicketComment(ticket_id=t.id, author_id=user.id, body=body, ai_assisted=ai_assisted)
    db.add(comment)
    if t.first_response_at is None:
        t.first_response_at = _now()
    t.updated_at = _now()
    await db.flush()
    _event(db, t, "comment_added", user, comment_id=comment.id, ai_assisted=ai_assisted)
    await _done(db)
    await db.refresh(comment, ["author"])
    return comment


async def add_attachment(db: AsyncSession, user: User, ticket_id: int, upload: UploadFile) -> TicketAttachment:
    t = await get_ticket(db, user, ticket_id)
    stored = await storage.save_upload(upload)
    try:
        att = TicketAttachment(
            ticket_id=t.id,
            uploaded_by_id=user.id,
            filename=stored.filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            storage_key=stored.storage_key,
        )
        db.add(att)
        t.updated_at = _now()
        await db.flush()
        _event(db, t, "attachment_added", user, attachment_id=att.id, filename=att.filename, size=att.size_bytes)
        await _done(db)
    except BaseException:
        storage.delete(stored.storage_key)
        raise
    await db.refresh(att, ["uploaded_by"])
    return att


async def get_attachment(db: AsyncSession, user: User, ticket_id: int, attachment_id: int) -> TicketAttachment:
    t = await get_ticket(db, user, ticket_id)
    att = await repo.attachment(db, t.id, attachment_id)
    if att is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return att


# ------------------------------------------------------------------------------------------------ copilot
async def generate_copilot(db: AsyncSession, user: User, ticket_id: int) -> AIAnalysis:
    """Ask the LLM for a summary, key issues, recommendations and a draft response (PII masked first)."""
    t = await get_ticket(db, user, ticket_id)
    context = {
        "category": t.category,
        "intent": t.intent,
        "sentiment": t.sentiment,
        "priority": t.priority,
        "channel": t.channel,
        "product": t.product,
        "amount_inr": t.amount_inr,
        "entities": t.entities,
    }
    # The OpenAI SDK call is blocking; run it in a worker thread.
    run = await asyncio.to_thread(
        generate_insight, t.description, context, [t.customer_name] if t.customer_name else None
    )
    analysis = triage_analysis(t)
    analysis.kind = "copilot"
    analysis.summary = run.insight.summary
    analysis.key_issues = run.insight.key_issues
    analysis.recommendations = run.insight.recommended_actions
    analysis.draft_response = run.insight.customer_reply
    analysis.provider = run.provider
    analysis.model = (run.usage or {}).get("model") or run.model
    analysis.prompt_version = PROMPT_VERSION
    analysis.usage = run.usage
    await repo.add_analysis(db, analysis)
    _event(
        db,
        t,
        "copilot_generated",
        user,
        analysis_id=analysis.id,
        provider=analysis.provider,
        prompt_version=PROMPT_VERSION,
    )
    await db.commit()
    await db.refresh(t, ["analyses"])
    return analysis


OPEN_STATUS_VALUES = sorted(s.value for s in OPEN_STATUSES)
