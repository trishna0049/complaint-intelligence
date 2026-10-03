"""Rule-based entity extraction: rupee amounts, order IDs, dates, products, repeat-contact cues."""

from __future__ import annotations

import re
from typing import Any

_NUM = r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?"
AMOUNT = re.compile(
    rf"(?:₹|rs\.?|inr)\s*({_NUM})(?:\s*(k|lakh|lac))?|({_NUM})(?:\s*(k|lakh|lac))?\s*(?:rupees|rs\b|inr\b|/-)",
    re.I,
)
ORDER_ID = re.compile(
    r"\b(?:order(?:\s*(?:id|no\.?|number|#))?\s*[:#]?\s*)([A-Z]{0,4}[-]?\d{5,}[A-Z0-9-]*)"
    r"|\b(OD[-]?\d{6,})\b"
    r"|\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.I,
)
DATE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+\d{4})?"
    r"|(?:yesterday|today|last week|last month))\b",
    re.I,
)
REPEAT = re.compile(
    r"(already|again|multiple times|many times|several times|(?:two|three|four|five|\d+)\s+times|"
    r"\d+(?:st|nd|rd|th)\s+time|still not|no one (?:has )?(?:helped|responded)|follow(?:ed)?[- ]up)",
    re.I,
)
PRODUCTS = {
    "Mobile": ["phone", "mobile", "iphone", "smartphone", "charger"],
    "Electronics": ["laptop", "tv", "television", "headphone", "earphone", "camera", "speaker", "tablet", "watch"],
    "Home Appliances": ["refrigerator", "fridge", "washing machine", "ac", "air conditioner", "microwave", "mixer"],
    "Furniture": ["sofa", "bed", "table", "chair", "mattress", "wardrobe"],
    "LifeStyle": ["shoe", "shoes", "shirt", "dress", "jeans", "bag", "kurta", "saree"],
    "Books & General merchandise": ["book", "books", "toy", "stationery"],
    "GiftCard": ["gift card", "voucher"],
}
_MULT = {"k": 1_000, "lakh": 100_000, "lac": 100_000}


def _to_number(raw: str, unit: str | None) -> float:
    value = float(raw.replace(",", ""))
    return value * _MULT.get((unit or "").lower(), 1)


def extract_entities(text: str) -> dict[str, Any]:
    text = text or ""
    amounts: list[dict[str, Any]] = []
    for m in AMOUNT.finditer(text):
        raw, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        value = _to_number(raw, unit)
        if value > 0:
            amounts.append({"text": m.group(0).strip(), "value": value})
    order_ids = [next(g for g in m.groups() if g) for m in ORDER_ID.finditer(text)]
    dates = [m.group(1) for m in DATE.finditer(text)]
    lower = f" {text.lower()} "
    products = sorted(
        {cat for cat, words in PRODUCTS.items() if any(re.search(rf"\b{re.escape(w)}\b", lower) for w in words)}
    )
    return {
        "amounts": amounts,
        "max_amount_inr": max((a["value"] for a in amounts), default=None),
        "order_ids": list(dict.fromkeys(order_ids)),
        "dates": list(dict.fromkeys(dates)),
        "products": products,
        "repeat_contact": bool(REPEAT.search(text)),
    }
