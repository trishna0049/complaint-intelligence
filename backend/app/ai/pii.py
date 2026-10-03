"""Mask personal data before any text is sent to the LLM.

Order IDs and rupee amounts are kept: they are needed to understand the complaint and do not
identify a person.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    # UPI handles look like e-mails without a domain dot (name@okaxis, 98xxxxxx@ybl); applied after EMAIL.
    ("UPI", re.compile(r"\b[A-Za-z0-9._-]{2,}@[A-Za-z]{2,}\b(?!\.[A-Za-z])")),
    # 13-19 digit card numbers, optionally grouped by spaces/dashes
    ("CARD", re.compile(r"\b(?:\d[ -]?){12,18}\d\b")),
    # Aadhaar: 12 digits, usually 4-4-4
    ("AADHAAR", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    # Indian mobile numbers with optional +91 / 0 prefix
    ("PHONE", re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("PINCODE", re.compile(r"\b(?:pin(?:code)?|pin code)\s*[:\-]?\s*\d{6}\b", re.I)),
]

_NAME_INTRO = re.compile(r"\b((?i:my name is|this is|i am))\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")


def mask_pii(text: str, known_names: list[str] | None = None) -> str:
    """Replace personal data with typed placeholders like [EMAIL] or [PHONE]."""
    if not text:
        return text
    out = text
    for label, pattern in _PATTERNS:
        out = pattern.sub(f"[{label}]", out)
    out = _NAME_INTRO.sub(lambda m: f"{m.group(1)} [NAME]", out)
    for name in known_names or []:
        if name and len(name) > 1:
            out = re.sub(re.escape(name), "[NAME]", out, flags=re.I)
    return out
