"""Bring imported history up to what the current importer produces (idempotent):

* entities for dataset remarks that have none (amounts, order ids, products, repeat-contact cues);
* the priority rules re-applied with the repeat cue (raise-only: a repeat contact can only raise priority) — a ticket
  whose priority changes has its SLA outcome re-scored against the new priority;
* SLA outcomes for resolved / closed tickets that never had one (app.services.sla.score_history).

Usage:  python -m scripts.backfill_history   (.\\scripts\\dev.ps1 backfill)
"""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import or_, select, text, update

from app.ai.entities import extract_entities
from app.ai.priority import decide_priority
from app.core.db import SessionLocal, dispose_engine
from app.models import Ticket
from app.services.sla import score_history

BATCH = 2000
SLA_RESET = {
    "sla_policy_id": None,
    "sla_target_seconds": None,
    "sla_started_at": None,
    "sla_deadline": None,
    "sla_stopped_at": None,
    "sla_breached_at": None,
    "sla_status": "none",
}


async def run() -> dict[str, int]:
    started = time.perf_counter()
    counts = {"entities": 0, "repriced": 0, "sla_scored": 0}
    async with SessionLocal() as db:
        last_id = 0
        while True:
            rows = (
                await db.execute(
                    select(
                        Ticket.id,
                        Ticket.description,
                        Ticket.category,
                        Ticket.intent,
                        Ticket.sentiment,
                        Ticket.amount_inr,
                        Ticket.priority,
                    )
                    .where(
                        Ticket.id > last_id,
                        Ticket.source == "dataset",
                        Ticket.description_source == "dataset_remark",
                        or_(Ticket.entities.is_(None), text("tickets.entities = 'null'::jsonb")),
                    )
                    .order_by(Ticket.id)
                    .limit(BATCH)
                )
            ).all()
            if not rows:
                break
            last_id = rows[-1].id
            plain, repriced = [], []
            for r in rows:
                entities = extract_entities(r.description)
                decision = decide_priority(
                    r.category, r.sentiment, r.amount_inr, entities["repeat_contact"], r.intent, r.description
                )
                reasons = [
                    {"rule": "BASE", "reason": f"Base priority for {r.category}", "from": "", "to": decision.base},
                    *decision.reasons,
                ]
                if decision.priority != r.priority:
                    repriced.append(
                        {"id": r.id, "entities": entities, "priority": decision.priority, "priority_reasons": reasons}
                        | SLA_RESET
                    )
                else:
                    plain.append({"id": r.id, "entities": entities})
            if plain:  # ORM bulk UPDATE by primary key
                await db.execute(update(Ticket), plain)
            if repriced:
                await db.execute(update(Ticket), repriced)
            await db.commit()
            counts["entities"] += len(rows)
            counts["repriced"] += len(repriced)
            print(f"entities for {counts['entities']:,} remarks ({counts['repriced']:,} re-prioritised)")
        counts["sla_scored"] = await score_history(db)
        await db.commit()
    await dispose_engine()
    print(
        f"done in {time.perf_counter() - started:.1f}s: entities {counts['entities']:,}, "
        f"priority raised {counts['repriced']:,}, SLA outcomes scored {counts['sla_scored']:,}"
    )
    return counts


if __name__ == "__main__":
    asyncio.run(run())
