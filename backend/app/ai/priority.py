"""Rule-based priority (see docs/PRIORITY_RULES.md). The dataset has no priority labels, so
priority is decided by transparent business rules — never by the LLM.

Start from the category's base priority; each rule can only RAISE it (capped at Critical).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LEVELS = ["Low", "Medium", "High", "Critical"]

BASE_PRIORITY = {
    "Payments related": "High",
    "Refund Related": "High",
    "Returns": "Medium",
    "Order Related": "Medium",
    "Cancellation": "Medium",
    "Shopzilla Related": "Medium",
    "App/website": "Medium",
    "Product Queries": "Low",
    "Feedback": "Low",
    "Offers & Cashback": "Low",
    "Onboarding related": "Low",
    "Others": "Low",
}

HIGH_AMOUNT = 10_000
VERY_HIGH_AMOUNT = 50_000
FRAUD = re.compile(r"\b(fraud\w*|scam\w*|unauthori[sz]ed|hack(?:ed|ing)?|stolen|phishing)\b", re.I)
LEGAL = re.compile(r"\b(consumer (?:court|forum)|legal (?:action|notice)|lawyer|police complaint|ombudsman)\b", re.I)


@dataclass
class PriorityDecision:
    priority: str
    base: str
    reasons: list[dict[str, str]] = field(default_factory=list)


def decide_priority(
    category: str | None,
    sentiment: str | None = None,
    amount_inr: float | None = None,
    repeat_contact: bool = False,
    intent: str | None = None,
    text: str = "",
) -> PriorityDecision:
    base = BASE_PRIORITY.get(category or "", "Medium")
    level = LEVELS.index(base)
    reasons: list[dict[str, str]] = []

    def raise_to(new_level: int, rule: str, why: str) -> None:
        """Record every rule that matched; it only changes the level when it raises it."""
        nonlocal level
        new_level = max(level, min(new_level, len(LEVELS) - 1))
        reasons.append({"rule": rule, "reason": why, "from": LEVELS[level], "to": LEVELS[new_level]})
        level = new_level

    if sentiment == "Very Negative":
        raise_to(level + 1, "R1", "Very negative sentiment")
    elif sentiment == "Negative":
        raise_to(max(level, 1), "R2", "Negative sentiment is at least Medium")
    if amount_inr is not None and amount_inr >= HIGH_AMOUNT:
        raise_to(level + 1, "R3", f"Amount ₹{amount_inr:,.0f} ≥ ₹{HIGH_AMOUNT:,}")
    if amount_inr is not None and amount_inr >= VERY_HIGH_AMOUNT:
        raise_to(max(level, 2), "R4", f"Amount ≥ ₹{VERY_HIGH_AMOUNT:,} is at least High")
    if repeat_contact:
        raise_to(level + 1, "R5", "Customer has contacted support before")
    if intent == "Fraudulent User" or FRAUD.search(text or ""):
        raise_to(max(level, 2), "R6", "Fraud / account-security signal")
    if LEGAL.search(text or ""):
        raise_to(max(level, 2), "R7", "Legal or regulatory escalation threat")

    return PriorityDecision(priority=LEVELS[level], base=base, reasons=reasons)
