"""Backfill ticket embeddings (MiniLM, 384 dims) for similar-ticket search and copilot grounding.

Only tickets with real complaint text are embedded: everything typed in the app, plus dataset remarks of at least
four words — templated descriptions and one-word survey remarks ("Good", "Thank you") say nothing about a problem.
Idempotent and resumable: tickets that already have a vector for the current model are skipped.

Usage:  python -m scripts.embed_tickets [--batch 2000] [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import time

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert

from app.ai.embeddings import embed, get_embedder, ticket_text, worth_embedding
from app.core.db import SessionLocal, dispose_engine
from app.models import Ticket, TicketEmbedding


async def run(batch: int = 2000, limit: int | None = None) -> int:
    model = get_embedder().name
    started, done, last_id = time.perf_counter(), 0, 0
    async with SessionLocal() as db:
        while True:
            rows = (
                await db.execute(
                    select(Ticket.id, Ticket.subject, Ticket.description, Ticket.source, Ticket.description_source)
                    .where(
                        Ticket.id > last_id,
                        Ticket.description_source != "template",
                        ~exists().where(TicketEmbedding.ticket_id == Ticket.id, TicketEmbedding.model_name == model),
                    )
                    .order_by(Ticket.id)
                    .limit(batch)
                )
            ).all()
            if not rows:
                break
            last_id = rows[-1].id
            todo = [r for r in rows if worth_embedding(r.description_source, r.description)]
            if limit is not None:
                todo = todo[: max(0, limit - done)]
            if todo:
                texts = [ticket_text(r.subject if r.source == "new" else None, r.description) for r in todo]
                vectors = await asyncio.to_thread(embed, texts)
                await db.execute(
                    insert(TicketEmbedding)
                    .values(
                        [
                            {"ticket_id": r.id, "embedding": v.tolist(), "model_name": model}
                            for r, v in zip(todo, vectors, strict=True)
                        ]
                    )
                    .on_conflict_do_nothing(constraint="uq_ticket_embeddings_ticket_model")
                )
                await db.commit()
                done += len(todo)
            print(f"embedded {done:,} tickets (scanned up to id {last_id:,})")
            if limit is not None and done >= limit:
                break
    await dispose_engine()
    print(f"done: {done:,} new embeddings with {model} in {time.perf_counter() - started:.1f}s")
    return done


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=2000)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run(args.batch, args.limit))


if __name__ == "__main__":
    main()
