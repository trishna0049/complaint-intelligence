"""Validate the pretrained Hugging Face sentiment model against the dataset's CSAT scores.

The model (nlptown/bert-base-multilingual-uncased-sentiment) predicts 1–5 stars; CSAT is the
customer's own 1–5 rating, so the two are directly comparable. Runs on every row with a real remark.

Outputs: ml/artifacts/sentiment_predictions.csv  (used by the dataset importer)
         ml/reports/sentiment_report.md, ml/reports/sentiment_vs_csat.png

Usage:  python ml/eval_sentiment.py [--limit N]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("HF_HOME", str(ROOT / "ml" / ".hf_cache"))  # keep model downloads inside the project
sys.path.insert(0, str(ROOT / "backend"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support  # noqa: E402

from app.ai.sentiment import LABELS, TransformerSentiment  # noqa: E402
from app.core.config import get_settings  # noqa: E402

ARTIFACTS = ROOT / "ml" / "artifacts"
REPORTS = ROOT / "ml" / "reports"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(ROOT / "data" / "ecommerce_support.csv", usecols=["Unique id", "Customer Remarks", "CSAT Score"])
    df["text"] = df["Customer Remarks"].fillna("").astype(str).str.strip()
    df = df[df["text"] != ""].reset_index(drop=True)
    if args.limit:
        df = df.sample(args.limit, random_state=42).reset_index(drop=True)
    model_name = get_settings().sentiment_model
    model = TransformerSentiment(model_name)
    t0 = time.perf_counter()
    preds = model.predict_many(df["text"].tolist(), batch_size=64)
    elapsed = time.perf_counter() - t0
    df["sentiment"] = [p.label for p in preds]
    df["stars"] = [LABELS.index(p.label) + 1 for p in preds]
    df["expected_stars"] = [p.score for p in preds]
    df["confidence"] = [p.confidence for p in preds]
    df[["Unique id", "sentiment", "expected_stars", "confidence"]].rename(columns={"Unique id": "unique_id"}).to_csv(
        ARTIFACTS / "sentiment_predictions.csv", index=False
    )

    csat = df["CSAT Score"].astype(int)
    exact = float((df["stars"] == csat).mean())
    within1 = float(((df["stars"] - csat).abs() <= 1).mean())
    rho, _ = spearmanr(df["expected_stars"], csat)
    # Binary view: does the model flag dissatisfied customers (CSAT 1-2)?
    y_true = csat <= 2
    y_pred = df["stars"] <= 2
    p, r, f, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    majority_exact = float((csat == csat.mode()[0]).mean())

    cm = confusion_matrix(csat, df["stars"], labels=[1, 2, 3, 4, 5])
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    norm = cm / cm.sum(axis=1, keepdims=True)
    ax.imshow(norm, cmap="Purples", vmin=0, vmax=1)
    for i in range(5):
        for j in range(5):
            ax.text(
                j,
                i,
                f"{cm[i, j]:,}\n{norm[i, j]:.0%}",
                ha="center",
                va="center",
                fontsize=7.5,
                color="white" if norm[i, j] > 0.5 else "black",
            )
    ax.set_xticks(range(5), [f"{i}★\n{LABELS[i - 1]}" for i in range(1, 6)], fontsize=7)
    ax.set_yticks(range(5), [f"CSAT {i}" for i in range(1, 6)], fontsize=8)
    ax.set_xlabel("Model sentiment")
    ax.set_ylabel("Customer's CSAT score")
    ax.set_title("Sentiment model vs CSAT (rows with remarks)")
    fig.tight_layout()
    fig.savefig(REPORTS / "sentiment_vs_csat.png", dpi=130)
    plt.close(fig)

    by_level = df.groupby("sentiment")["CSAT Score"].agg(["count", "mean"]).reindex(LABELS)
    lines = [
        "# Sentiment model validation against CSAT\n",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `ml/eval_sentiment.py`.\n",
        f"Model: `{model_name}` (pretrained, not fine-tuned). Rows: {len(df):,} remarks; "
        f"inference {elapsed:.0f}s on CPU ({len(df) / elapsed:.0f} texts/s).\n",
        "## Agreement with CSAT\n",
        "| Metric | Value |",
        "|---|---|",
        f"| Exact match (stars = CSAT) | {exact:.1%} |",
        f"| Within ±1 star | {within1:.1%} |",
        f"| Spearman correlation (expected stars vs CSAT) | {rho:.3f} |",
        "| Dissatisfied detection (CSAT ≤ 2 vs predicted ≤ 2): precision / recall / F1 | "
        f"{p:.3f} / {r:.3f} / {f:.3f} |",
        f"| Reference: always predicting the most common CSAT | {majority_exact:.1%} exact |",
        "",
        "## Mean CSAT by predicted sentiment\n",
        "| Predicted sentiment | Rows | Mean CSAT |",
        "|---|---|---|",
        *[
            f"| {lvl} | {int(row['count']) if row['count'] == row['count'] else 0:,} | {row['mean']:.2f} |"
            for lvl, row in by_level.iterrows()
            if row["count"] == row["count"]
        ],
        "",
        "![Confusion matrix](sentiment_vs_csat.png)\n",
        "## Notes\n",
        "- CSAT rates the whole support interaction while the model reads only the remark text, so perfect agreement "
        "is not expected; a monotonic rise in mean CSAT across predicted levels is the main validity check.\n",
        '- Remarks are very short; one-word remarks such as "ok" are inherently ambiguous.\n',
        "- Predictions are saved to `ml/artifacts/sentiment_predictions.csv` and reused by the dataset importer.\n",
    ]
    (REPORTS / "sentiment_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"exact={exact:.3f} within1={within1:.3f} spearman={rho:.3f} dissatisfied P/R/F1={p:.3f}/{r:.3f}/{f:.3f}")
    print(by_level)


if __name__ == "__main__":
    np.random.seed(0)
    main()
