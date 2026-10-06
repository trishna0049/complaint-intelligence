"""The four consumers (one Kafka consumer group each)."""

from __future__ import annotations

from app.events.consumer import Consumer
from app.workers import ai, llm, notification, sla

CONSUMERS: list[Consumer] = [ai.CONSUMER, llm.CONSUMER, sla.CONSUMER, notification.CONSUMER]
BY_NAME: dict[str, Consumer] = {c.name: c for c in CONSUMERS}
