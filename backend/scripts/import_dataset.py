"""Import the historical dataset into the tickets table (idempotent).

* Rows are keyed on the dataset's `Unique id`; re-running skips rows already imported (pre-filtered, and
  `ON CONFLICT DO NOTHING` guards against a concurrent run).
* Inserted in batches (default 5,000 rows per transaction), so a failure loses at most one batch.
* Category / intent come from the dataset's own labels (labels_from='dataset').
* Sentiment comes from the offline Hugging Face run (ml/artifacts/sentiment_predictions.csv) when present.
* Priority uses the same rules as live complaints (category, sentiment, amount, text cues).
* Empty remarks get a templated description (description_source='template', excluded from model training).
* `Issue_reported at` becomes created_at and `issue_responded` the first-response time (also used as the
  resolution time: every historical contact was closed in that interaction).
* Every historical contact was handled and surveyed, so imported tickets are CLOSED.
* After the insert, `link_history` sets each ticket's assignee (the dataset's Agent_name, seeded as a user by
  scripts/seed.py) and team (the team that owns the ticket's category). It only fills empty links, so it is safe
  to re-run — run the seed first, or re-run the import after seeding to link existing rows.
* Timestamps are shifted by whole days so the newest record lands yesterday, which keeps the dashboard's
  "last 7 / 30 days" and "this week vs last week" views meaningful (relative spacing is preserved).

Usage:  python -m scripts.import_dataset [--csv PATH] [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import column, select, table, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.priority import decide_priority
from app.core.config import REPO_DIR, get_settings
from app.core.db import SessionLocal, dispose_engine
from app.models import Category, Ticket, User

TS = "%d/%m/%Y %H:%M"


COLUMNS = {
    "Unique id": "uid",
    "channel_name": "channel",
    "Sub-category": "intent",
    "Order_id": "order_id",
    "Product_category": "product",
    "Item_price": "price",
    "Customer_City": "city",
    "CSAT Score": "csat",
}


def template_text(channel: str, category: str, intent: str) -> str:
    return f"[No customer remarks recorded] {channel} contact about {category} — {intent}."


def day_shift(latest: datetime, now: datetime) -> timedelta:
    """Whole-day offset that moves the newest record to yesterday (never into the future)."""
    return timedelta(days=(now.date() - latest.date()).days - 1)


async def run(csv_path: Path, limit: int | None = None, shift_to_now: bool = True, batch: int = 5000) -> int:
    started = time.perf_counter()
    df = pd.read_csv(csv_path, nrows=limit)
    df["reported"] = pd.to_datetime(df["Issue_reported at"], format=TS, errors="coerce")
    df["responded"] = pd.to_datetime(df["issue_responded"], format=TS, errors="coerce")
    df = df[df["reported"].notna()].copy()
    df["remark"] = df["Customer Remarks"].fillna("").astype(str).str.strip()

    preds = get_settings().artifacts_dir / "sentiment_predictions.csv"
    if preds.is_file():
        s = pd.read_csv(preds, usecols=["unique_id", "sentiment", "expected_stars"])
        df = df.merge(s, how="left", left_on="Unique id", right_on="unique_id")
    else:
        print(f"note: {preds} not found - imported sentiment left empty (run ml/eval_sentiment.py)")
        df["sentiment"], df["expected_stars"] = None, None

    now = datetime.now(UTC)
    latest = df["reported"].max().to_pydatetime().replace(tzinfo=UTC)
    shift = day_shift(latest, now) if shift_to_now else timedelta(0)

    async with SessionLocal() as db:
        existing = set((await db.scalars(select(Ticket.external_id).where(Ticket.external_id.is_not(None)))).all())
        todo = df[~df["Unique id"].isin(existing)]
        rows = []
        for r in todo.rename(columns=COLUMNS).itertuples(index=False):
            amount = None if pd.isna(r.price) else float(r.price)
            sentiment = r.sentiment if isinstance(r.sentiment, str) else None
            decision = decide_priority(r.category, sentiment, amount, False, r.intent, r.remark)
            created = r.reported.to_pydatetime().replace(tzinfo=UTC) + shift
            responded = None if pd.isna(r.responded) else r.responded.to_pydatetime().replace(tzinfo=UTC) + shift
            if responded is not None and responded < created:
                responded = None  # negative response times in the source are invalid
            rows.append(
                {
                    "external_id": r.uid,
                    "source": "dataset",
                    "subject": f"{r.intent} — {r.category}",
                    "description": r.remark or template_text(r.channel, r.category, r.intent),
                    "description_source": "dataset_remark" if r.remark else "template",
                    "channel": r.channel,
                    "order_id": None if pd.isna(r.order_id) else r.order_id,
                    "product": None if pd.isna(r.product) else r.product,
                    "amount_inr": amount,
                    "city": None if pd.isna(r.city) else str(r.city).strip().title(),
                    "status": "CLOSED",
                    "csat_score": int(r.csat),
                    "created_at": created,
                    "updated_at": responded or created,
                    "first_response_at": responded,
                    "resolved_at": responded or created,
                    "closed_at": responded or created,
                    "category": r.category,
                    "intent": r.intent,
                    "sentiment": sentiment,
                    "sentiment_score": None if pd.isna(r.expected_stars) else float(r.expected_stars),
                    "priority": decision.priority,
                    "priority_reasons": [
                        {"rule": "BASE", "reason": f"Base priority for {r.category}", "from": "", "to": decision.base},
                        *decision.reasons,
                    ],
                    "entities": None,
                    "needs_review": False,
                    "labels_from": "dataset",
                    "model_version": None,
                }
            )
        inserted = 0  # rows actually written (a concurrent run may have inserted some)
        for i in range(0, len(rows), batch):
            stmt = insert(Ticket).on_conflict_do_nothing(index_elements=[Ticket.external_id]).returning(Ticket.id)
            result = await db.execute(stmt, rows[i : i + batch])
            inserted += len(result.all())
            await db.commit()
            print(f"imported {min(i + batch, len(rows)):,} / {len(rows):,}")
        linked = await link_history(db, df[["Unique id", "Agent_name"]])
    await dispose_engine()
    print(
        f"linked {linked['assignee']:,} tickets to their agent and {linked['team']:,} to a team; "
        f"done: {inserted:,} new rows ({len(df) - len(rows):,} already present) in {time.perf_counter() - started:.1f}s"
    )
    return inserted


async def link_history(db: AsyncSession, agents: pd.DataFrame, batch: int = 10_000) -> dict[str, int]:
    """Fill tickets.assignee_id from Agent_name and tickets.team_id from the category's owning team (idempotent)."""
    users = {
        name: uid for uid, name in (await db.execute(select(User.id, User.name).where(User.source == "dataset"))).all()
    }
    team_rows = await db.execute(
        update(Ticket)
        .where(Ticket.team_id.is_(None), Ticket.category == Category.name, Category.team_id.is_not(None))
        .values(team_id=Category.team_id)
    )
    if not users:
        await db.commit()
        print("note: no dataset agents found - run scripts.seed, then re-run the import to link assignees")
        return {"assignee": 0, "team": team_rows.rowcount or 0}
    pairs = [
        {"external_id": uid, "assignee_id": users[name]}
        for uid, name in agents.dropna().itertuples(index=False)
        if name in users
    ]
    await db.execute(
        text("CREATE TEMP TABLE _assign (external_id varchar(64) PRIMARY KEY, assignee_id int) ON COMMIT DROP")
    )
    tmp = table("_assign", column("external_id"), column("assignee_id"))
    for i in range(0, len(pairs), batch):
        await db.execute(tmp.insert(), pairs[i : i + batch])
    assigned = await db.execute(
        text(
            "UPDATE tickets t SET assignee_id = a.assignee_id FROM _assign a "
            "WHERE t.external_id = a.external_id AND t.assignee_id IS NULL"
        )
    )
    await db.commit()
    return {"assignee": assigned.rowcount or 0, "team": team_rows.rowcount or 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(REPO_DIR / "data" / "ecommerce_support.csv"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-shift", action="store_true", help="keep the original 2023 timestamps")
    parser.add_argument("--batch", type=int, default=5000)
    args = parser.parse_args()
    asyncio.run(run(Path(args.csv), args.limit, shift_to_now=not args.no_shift, batch=args.batch))


if __name__ == "__main__":
    main()
