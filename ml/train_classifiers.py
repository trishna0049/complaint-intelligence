"""Train and evaluate the category and intent classifiers.

Data: rows of data/ecommerce_support.csv that have real `Customer Remarks` (templated/empty rows are
excluded). Labels: `category` (12 classes) and `Sub-category` (intent).
Split: 70 / 15 / 15 stratified by category (train / validation / test), fixed seed.

Candidates (scikit-learn):
  A. baseline        TF-IDF(word 1-2 + char 2-5) on the text -> Logistic Regression
  B. text+structured  A + one-hot channel / product / price bucket / has-order-id -> Logistic Regression
Each with and without class balancing. The best by validation macro-F1 wins per task (within 0.005 counts
as a tie, broken by accuracy); it is then refit
on train+validation and scored once on the untouched test set. The keyword prior (backend/app/ai/keywords.py)
is kept for category only if it does not lower validation macro-F1.

Outputs: ml/artifacts/{category_model,intent_model}.joblib, classifier_meta.json,
         ml/reports/classifier_report.md, ml/reports/category_confusion.png

Usage:  python ml/train_classifiers.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.classifier import price_bucket  # noqa: E402
from app.ai.keywords import blend_with_prior  # noqa: E402

ARTIFACTS = ROOT / "ml" / "artifacts"
REPORTS = ROOT / "ml" / "reports"
SEED = 42
VERSION = "triage-v1"
TIE = 0.005  # macro-F1 difference treated as a tie during model selection


def load() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / "ecommerce_support.csv")
    df["text"] = df["Customer Remarks"].fillna("").astype(str).str.strip()
    df = df[df["text"] != ""].copy()  # exclude rows that would get a templated description
    df["channel"] = df["channel_name"].fillna("Unknown")
    df["product"] = df["Product_category"].fillna("Unknown")
    df["price_bucket"] = df["Item_price"].map(lambda v: price_bucket(None if pd.isna(v) else float(v)))
    df["has_order_id"] = np.where(df["Order_id"].notna(), "yes", "no")
    df["intent"] = df["Sub-category"]
    return df


def text_features() -> FeatureUnion:
    return FeatureUnion(
        [
            ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, strip_accents="unicode")),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb", ngram_range=(2, 5), min_df=3, sublinear_tf=True, max_features=60000
                ),
            ),
        ]
    )


def make_model(kind: str, balanced: bool) -> Pipeline:
    if kind == "baseline":
        features = ColumnTransformer([("text", text_features(), "text")])
    else:
        features = ColumnTransformer(
            [
                ("text", text_features(), "text"),
                ("cat", OneHotEncoder(handle_unknown="ignore"), ["channel", "product", "price_bucket", "has_order_id"]),
            ]
        )
    clf = LogisticRegression(max_iter=3000, C=2.0, class_weight="balanced" if balanced else None)
    return Pipeline([("features", features), ("clf", clf)])


def scores(y_true, y_pred) -> dict[str, float]:
    p, r, f, _ = precision_recall_fscore_support(y_true, y_pred, average="macro", zero_division=0)
    _, _, fw, _ = precision_recall_fscore_support(y_true, y_pred, average="weighted", zero_division=0)
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_precision": p,
        "macro_recall": r,
        "macro_f1": f,
        "weighted_f1": fw,
    }


def select(task: str, X_tr, y_tr, X_va, y_va) -> tuple[str, bool, list[dict]]:
    results = []
    for kind in ("baseline", "text+structured"):
        for balanced in (False, True):
            t0 = time.perf_counter()
            m = make_model(kind, balanced).fit(X_tr, y_tr)
            s = scores(y_va, m.predict(X_va))
            results.append({"task": task, "model": kind, "balanced": balanced, **s, "fit_s": time.perf_counter() - t0})
            print(
                f"  {task:8s} {kind:16s} balanced={balanced!s:5s} "
                f"val macro-F1={s['macro_f1']:.3f} acc={s['accuracy']:.3f}"
            )
    # Highest macro-F1 wins; candidates within 0.005 of it are a tie, broken by accuracy (class balancing can
    # buy a sliver of macro-F1 while destroying accuracy on these near-uninformative remarks).
    top = max(r["macro_f1"] for r in results)
    best = max((r for r in results if r["macro_f1"] >= top - TIE), key=lambda r: r["accuracy"])
    return best["model"], best["balanced"], results


def plot_confusion(y_true, y_pred, labels, path: Path, title: str) -> None:
    cm = confusion_matrix(y_true, y_pred, labels=labels, normalize="true")
    fig, ax = plt.subplots(figsize=(10, 8.5))
    im = ax.imshow(cm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(labels)), labels, fontsize=8)
    for i in range(len(labels)):
        for j in range(len(labels)):
            if cm[i, j] >= 0.01:
                ax.text(
                    j,
                    i,
                    f"{cm[i, j]:.2f}",
                    ha="center",
                    va="center",
                    fontsize=6.5,
                    color="white" if cm[i, j] > 0.5 else "black",
                )
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)
    fig.colorbar(im, fraction=0.046)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def fmt_table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        out.append("| " + " | ".join(f"{r[c]:.3f}" if isinstance(r[c], float) else str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    df = load()
    print(f"training rows with real remarks: {len(df):,}")
    train, rest = train_test_split(df, test_size=0.30, random_state=SEED, stratify=df["category"])
    val, test = train_test_split(rest, test_size=0.50, random_state=SEED, stratify=rest["category"])
    cols = ["text", "channel", "product", "price_bucket", "has_order_id"]

    report: list[str] = []
    meta: dict = {
        "version": VERSION,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rows": {"train": len(train), "validation": len(val), "test": len(test)},
    }
    all_results: list[dict] = []
    final: dict[str, Pipeline] = {}
    test_rows: list[dict] = []

    for task, label in (("category", "category"), ("intent", "intent")):
        kind, balanced, results = select(task, train[cols], train[label], val[cols], val[label])
        all_results += results
        model = make_model(kind, balanced).fit(pd.concat([train, val])[cols], pd.concat([train, val])[label])
        final[task] = model
        pred = model.predict(test[cols])
        s = scores(test[label], pred)
        test_rows.append({"task": task, "model": f"{kind}{' (balanced)' if balanced else ''}", **s})
        meta[f"{task}_model"] = {"kind": kind, "balanced": balanced, "test": s}
        majority = test[label].value_counts().index[0]
        test_rows.append(
            {"task": task, "model": f"majority class ('{majority}')", **scores(test[label], [majority] * len(test))}
        )
        if task == "category":
            cat_pred_test, cat_model = pred, model

    # ---- keyword prior decision (validation) and fixed realistic complaints ----
    classes = list(cat_model.classes_)
    probe = make_model(meta["category_model"]["kind"], meta["category_model"]["balanced"]).fit(
        train[cols], train["category"]
    )
    pv = probe.predict_proba(val[cols])
    f_plain = f1_score(val["category"], np.array(classes)[pv.argmax(1)], average="macro")
    f_prior = f1_score(
        val["category"],
        np.array(classes)[blend_with_prior(val["text"].tolist(), pv, classes).argmax(1)],
        average="macro",
    )
    use_prior = f_prior >= f_plain - 0.005
    meta["category_keyword_prior"] = bool(use_prior)

    p_test = cat_model.predict_proba(test[cols])
    blended = np.array(classes)[blend_with_prior(test["text"].tolist(), p_test, classes).argmax(1)]
    test_rows.append({"task": "category", "model": "chosen + keyword prior", **scores(test["category"], blended)})

    fixed = pd.read_csv(ROOT / "ml" / "data" / "fixed_complaints.csv")
    fx = pd.DataFrame(
        {"text": fixed["text"], "channel": "Web", "product": "Unknown", "price_bucket": "none", "has_order_id": "no"}
    )
    pf = cat_model.predict_proba(fx)
    fixed_plain = accuracy_score(fixed["category"], np.array(classes)[pf.argmax(1)])
    fixed_prior = accuracy_score(
        fixed["category"], np.array(classes)[blend_with_prior(fixed["text"].tolist(), pf, classes).argmax(1)]
    )
    meta["fixed_complaints_accuracy"] = {"model": fixed_plain, "model+keyword_prior": fixed_prior, "n": len(fixed)}

    # ---- save ----
    joblib.dump(final["category"], ARTIFACTS / "category_model.joblib", compress=3)
    joblib.dump(final["intent"], ARTIFACTS / "intent_model.joblib", compress=3)
    meta["intents_by_category"] = {c: sorted(g["intent"].unique().tolist()) for c, g in df.groupby("category")}
    (ARTIFACTS / "classifier_meta.json").write_text(json.dumps(meta, indent=2, default=float), encoding="utf-8")

    plot_confusion(
        test["category"],
        cat_pred_test,
        classes,
        REPORTS / "category_confusion.png",
        "Category — normalised confusion matrix (test set)",
    )

    # ---- report ----
    report.append("# Classifier evaluation report\n")
    report.append(f"Generated {meta['trained_at']} by `ml/train_classifiers.py` (seed {SEED}).\n")
    report.append(
        f"Training data: the {len(df):,} dataset rows that have real `Customer Remarks` (rows with empty remarks are "
        f"excluded — their descriptions are templated and would leak the label). Split 70/15/15 stratified by "
        f"category → train {len(train):,} / validation {len(val):,} / test {len(test):,}.\n"
    )
    report.append("## Model selection (validation set)\n")
    report.append(fmt_table(all_results, ["task", "model", "balanced", "accuracy", "macro_f1", "weighted_f1"]) + "\n")
    report.append("## Held-out test set\n")
    report.append(
        fmt_table(
            test_rows, ["task", "model", "accuracy", "macro_precision", "macro_recall", "macro_f1", "weighted_f1"]
        )
        + "\n"
    )
    report.append(
        f"Keyword prior on validation macro-F1: {f_plain:.3f} without → {f_prior:.3f} with — "
        f"**{'kept' if use_prior else 'dropped'}**.\n"
    )
    report.append("## Realistic complaint text (fixed examples)\n")
    report.append(
        f"`ml/data/fixed_complaints.csv` holds {len(fixed)} hand-written complaints in the style the app receives. "
        f"Category accuracy: model alone **{fixed_plain:.0%}**, model + keyword prior **{fixed_prior:.0%}**.\n"
    )
    report.append("## Per-class results — category (test set)\n")
    report.append("```\n" + classification_report(test["category"], cat_pred_test, zero_division=0) + "```\n")
    report.append("![Category confusion matrix](category_confusion.png)\n")
    intent_pred = final["intent"].predict(test[cols])
    top_intents = test["intent"].value_counts().head(15).index
    report.append("## Per-class results — intent, 15 most frequent classes (test set)\n")
    report.append(
        "```\n" + classification_report(test["intent"], intent_pred, labels=top_intents, zero_division=0) + "```\n"
    )
    report.append(
        "## Reading these numbers\n"
        "The only free text in the dataset is the customer's post-contact survey remark (median 3 words; the most "
        'common are "good", "thank you", "nice"). Most remarks say nothing about *what* the problem was, so '
        "macro-F1 on the dataset is low for every model and the majority-class baseline is shown for reference. The "
        "fixed realistic examples show the deployed pipeline on complaint-style text. Low-confidence predictions are "
        "flagged `needs_review` in the app instead of being trusted blindly.\n"
    )
    (REPORTS / "classifier_report.md").write_text("\n".join(report), encoding="utf-8")
    print(
        json.dumps(
            {
                k: meta[k]
                for k in ("category_model", "intent_model", "category_keyword_prior", "fixed_complaints_accuracy")
            },
            indent=2,
            default=float,
        )
    )


if __name__ == "__main__":
    main()
