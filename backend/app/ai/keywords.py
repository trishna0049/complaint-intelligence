"""Domain keyword prior for category classification.

Why: the dataset's only free text is the post-contact survey remark (median 3 words, mostly
"good"/"thank you"), so a model trained on it rarely sees phrases like "charged twice". These
high-precision phrases nudge the model's probabilities toward the obvious category. The blend is
evaluated against the pure model in ml/reports/classifier_report.md — it is kept only because it
does not hurt held-out macro-F1 and clearly helps on realistic complaint text.
"""

from __future__ import annotations

import re

import numpy as np

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Payments related": [
        r"charged twice",
        r"double (?:charge|debit|payment)",
        r"deducted",
        r"payment (?:failed|pending|declined)",
        r"\bupi\b",
        r"\bemi\b",
        r"wallet",
        r"paylater",
        r"card (?:was )?(?:charged|debited)",
        r"transaction failed",
    ],
    "Refund Related": [r"refund", r"money back", r"not (?:yet )?credited", r"reimburse"],
    "Returns": [
        r"return(?:ed|ing)?\b",
        r"pick ?up",
        r"exchange",
        r"replace(?:ment)?",
        r"damaged",
        r"wrong (?:item|product)",
        r"defective",
        r"broken",
    ],
    "Order Related": [
        r"not (?:yet )?delivered",
        r"delay(?:ed)?",
        r"where is my order",
        r"track(?:ing)?",
        r"invoice",
        r"installation",
        r"\bdemo\b",
        r"delivery",
    ],
    "Cancellation": [r"cancel(?:led|lation)?"],
    "Offers & Cashback": [r"cashback", r"coupon", r"voucher", r"discount", r"\boffer\b"],
    "Shopzilla Related": [r"premium", r"membership", r"rewards?", r"supercoin"],
    "App/website": [r"\bapp\b", r"website", r"log ?in", r"otp", r"crash", r"error"],
    "Product Queries": [r"warranty", r"specification", r"service cent(?:er|re)", r"how (?:do|to) use"],
    "Feedback": [r"\brude\b", r"unprofessional", r"behaviou?r", r"executive was"],
    "Onboarding related": [r"seller", r"onboard", r"sign ?up", r"register"],
}

_COMPILED = {c: [re.compile(p, re.I) for p in pats] for c, pats in CATEGORY_KEYWORDS.items()}
PRIOR_WEIGHT = 0.6


def keyword_hits(text: str) -> dict[str, int]:
    return {c: sum(bool(p.search(text or "")) for p in pats) for c, pats in _COMPILED.items()}


def blend_with_prior(
    texts: list[str], proba: np.ndarray, classes: list[str], weight: float = PRIOR_WEIGHT
) -> np.ndarray:
    """Mix model probabilities with a keyword distribution: (1-w)·p_model + w·p_keywords (rows with hits only)."""
    out = proba.copy()
    index = {c: i for i, c in enumerate(classes)}
    for row, text in enumerate(texts):
        hits = keyword_hits(text)
        total = sum(hits.values())
        if total == 0:
            continue
        prior = np.zeros(len(classes))
        for c, n in hits.items():
            if n and c in index:
                prior[index[c]] = n / total
        out[row] = (1 - weight) * proba[row] + weight * prior
    return out
