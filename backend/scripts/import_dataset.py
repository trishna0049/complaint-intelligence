"""Import the historical dataset into the complaints table (idempotent).

* Rows are keyed on the dataset's `Unique id`; re-running skips rows already imported.
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
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import func, insert, select

from app.ai.priority import decide_priority
from app.config import REPO_DIR, get_settings
from app.db import SessionLocal, init_db
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


def run(csv_path: Path, limit: int | None = None, shift_to_now: bool = True, batch: int = 5000) -> int:
    started = time.perf_counter()
    init_db()
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

    with SessionLocal() as db:
        existing = set(db.scalars(select(Complaint.external_id).where(Complaint.external_id.is_not(None))))
        next_id = (db.scalar(select(func.max(Complaint.id))) or 0) + 1
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
                    "reference": f"CMP-{next_id:06d}",
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
            next_id += 1
        for i in range(0, len(rows), batch):
            db.execute(insert(Complaint), rows[i : i + batch])
            db.commit()
            print(f"imported {min(i + batch, len(rows)):,} / {len(rows):,}")
    print(
        f"done: {len(rows):,} new rows ({len(df) - len(rows):,} already present) "
        f"in {time.perf_counter() - started:.1f}s"
    )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(REPO_DIR / "data" / "ecommerce_support.csv"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-shift", action="store_true", help="keep the original 2023 timestamps")
    args = parser.parse_args()
    run(Path(args.csv), args.limit, shift_to_now=not args.no_shift)


if __name__ == "__main__":
    main()
