"""Import the historical dataset into the complaints table (idempotent).

* Rows are keyed on the dataset's `Unique id`; re-running skips rows already imported (pre-filtered, and
  `ON CONFLICT DO NOTHING` guards against a concurrent run).
* Inserted in batches (default 5,000 rows per transaction), so a failure loses at most one batch.
* Category / intent come from the dataset's own labels (labels_from='dataset').
* Sentiment comes from the offline Hugging Face run (ml/artifacts/sentiment_predictions.csv) when present.
* Priority uses the same rules as live complaints (category, sentiment, amount, text cues).
* Empty remarks get a templated text, flagged text_is_template (and excluded from model training).
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
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.ai.priority import decide_priority
from app.core.config import REPO_DIR, get_settings
from app.core.db import SessionLocal, dispose_engine
from app.models import Complaint

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
        existing = set(
            (await db.scalars(select(Complaint.external_id).where(Complaint.external_id.is_not(None)))).all()
        )
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
                    "text": r.remark or template_text(r.channel, r.category, r.intent),
                    "text_is_template": not r.remark,
                    "channel": r.channel,
                    "order_id": None if pd.isna(r.order_id) else r.order_id,
                    "product": None if pd.isna(r.product) else r.product,
                    "amount_inr": amount,
                    "city": None if pd.isna(r.city) else str(r.city).strip().title(),
                    "status": "Resolved",
                    "csat_score": int(r.csat),
                    "created_at": created,
                    "resolved_at": responded or created,
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
            stmt = (
                insert(Complaint).on_conflict_do_nothing(index_elements=[Complaint.external_id]).returning(Complaint.id)
            )
            result = await db.execute(stmt, rows[i : i + batch])
            inserted += len(result.all())
            await db.commit()
            print(f"imported {min(i + batch, len(rows)):,} / {len(rows):,}")
    await dispose_engine()
    print(
        f"done: {inserted:,} new rows ({len(df) - len(rows):,} already present) in {time.perf_counter() - started:.1f}s"
    )
    return inserted


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
