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


CUSTOMER = "[CUSTOMER]"  # the ticket's own customer: restored locally in the model's answer (see app.ai.llm)


def _mask_name(out: str, name: str, token: str) -> str:
    """The full name first, then each part on its own ("Meera" in "thanks, Meera"), as whole words of at least
    three letters so short fragments can't eat into other words."""
    out = re.sub(re.escape(name), token, out, flags=re.I)
    for part in name.split():
        if len(part) >= 3:
            out = re.sub(r"\b" + re.escape(part) + r"\b", token, out, flags=re.I)
    return out


def mask_pii(text: str, known_names: list[str] | None = None, customer_name: str | None = None) -> str:
    """Replace personal data with typed placeholders like [EMAIL] or [PHONE]. The ticket's own customer becomes
    [CUSTOMER], every other known name (commenters, other customers) [NAME]."""
    if not text:
        return text
    out = text
    for label, pattern in _PATTERNS:
        out = pattern.sub(f"[{label}]", out)
    if customer_name and len(customer_name.strip()) > 1:
        out = _mask_name(out, customer_name.strip(), CUSTOMER)
    out = _NAME_INTRO.sub(lambda m: f"{m.group(1)} [NAME]", out)
    for name in sorted({n.strip() for n in known_names or [] if n and len(n.strip()) > 1}, key=len, reverse=True):
        out = _mask_name(out, name, "[NAME]")
    return out
