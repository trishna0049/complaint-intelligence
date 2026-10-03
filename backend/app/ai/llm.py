"""LLM complaint insights: summary, key issues, recommended actions and a suggested reply.

* LLM_PROVIDER=openai uses the OpenAI API with structured outputs (the response is parsed into
  the `ComplaintInsight` schema, so it is always valid JSON with the right fields).
* LLM_PROVIDER=mock (default) produces realistic, deterministic output offline — no key needed.

Personal data is masked before the text leaves the process. The suggested reply is only a draft:
an agent must review it; nothing is ever sent to the customer automatically.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.ai.pii import mask_pii
from app.config import get_settings

log = logging.getLogger(__name__)

PROMPT_VERSION = "insight-v1"

SYSTEM_PROMPT = """You are a senior customer-support analyst for Shopzilla, an Indian e-commerce company.
Given one customer complaint and its automated triage, produce:
- summary: 1-2 sentences, neutral, factual.
- key_issues: 1-4 short noun phrases naming the concrete problems.
- recommended_actions: 2-5 imperative, specific next steps for the support agent (check systems, refund, escalate...).
- customer_reply: a short, empathetic draft reply the agent can edit. Do not promise anything you cannot verify;
  never invent order details, amounts or dates that are not in the complaint.
Placeholders like [EMAIL] or [PHONE] are masked personal data; keep them as-is."""


class ComplaintInsight(BaseModel):
    summary: str = Field(description="1-2 sentence neutral summary")
    key_issues: list[str] = Field(min_length=1, max_length=4)
    recommended_actions: list[str] = Field(min_length=1, max_length=5)
    customer_reply: str


class InsightProvider(Protocol):
    name: str
    model: str

    def generate(self, complaint_text: str, context: dict[str, Any]) -> ComplaintInsight: ...


def build_user_prompt(masked_text: str, context: dict[str, Any]) -> str:
    lines = [f"Complaint: {masked_text}"]
    for key in ("category", "intent", "sentiment", "priority", "channel", "product", "amount_inr"):
        if context.get(key) not in (None, ""):
            lines.append(f"{key.replace('_', ' ').title()}: {context[key]}")
    return "\n".join(lines)


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=30)
        self.model = model

    def generate(self, complaint_text: str, context: dict[str, Any]) -> ComplaintInsight:
        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(complaint_text, context)},
            ],
            response_format=ComplaintInsight,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no parsed content (possibly a refusal)")
        return parsed


# ----------------------------------------------------------------------------------- mock
PLAYBOOK: dict[str, dict[str, Any]] = {
    "Payments related": {
        "issue": "payment problem",
        "actions": [
            "Check the payment gateway logs for the order and confirm how many successful debits exist",
            "If a duplicate debit is confirmed, raise a reversal for the extra amount",
            "Share the refund reference number and expected timeline (5–7 business days) with the customer",
        ],
    },
    "Refund Related": {
        "issue": "refund not received",
        "actions": [
            "Look up the refund status and reference number for the order",
            "If the refund is past its SLA, escalate to the finance team with the transaction details",
            "Give the customer the refund reference and the bank's expected credit date",
        ],
    },
    "Returns": {
        "issue": "return / pickup problem",
        "actions": [
            "Verify the return request status and pickup slot in the logistics system",
            "Reschedule the reverse pickup or arrange a self-ship option",
            "Confirm the refund or replacement will start once the item is picked up",
        ],
    },
    "Order Related": {
        "issue": "order delivery problem",
        "actions": [
            "Check the shipment tracking and the last courier scan",
            "Contact the courier partner for an updated delivery date",
            "Offer cancellation with a full refund if the delay exceeds the promised date",
        ],
    },
    "Cancellation": {
        "issue": "cancellation request",
        "actions": [
            "Check whether the order has already shipped",
            "Cancel the order or initiate return-to-origin if it is in transit",
            "Confirm the refund timeline for prepaid orders",
        ],
    },
    "Product Queries": {
        "issue": "product question",
        "actions": [
            "Answer from the product specification and warranty terms",
            "Share the nearest authorised service centre if needed",
        ],
    },
    "Feedback": {
        "issue": "service quality feedback",
        "actions": [
            "Acknowledge the feedback and apologise for the experience",
            "Log the interaction for quality review with the team lead",
        ],
    },
    "Offers & Cashback": {
        "issue": "cashback / offer not applied",
        "actions": [
            "Verify the offer terms and the customer's eligibility",
            "Credit the cashback manually if the order qualified",
        ],
    },
}
DEFAULT_PLAY = {
    "issue": "customer issue",
    "actions": ["Review the customer's order and account history", "Resolve or route to the right specialist team"],
}


class MockProvider:
    """Deterministic, offline stand-in that builds realistic output from the triage results."""

    name = "mock"
    model = "mock-insight-v1"

    def generate(self, complaint_text: str, context: dict[str, Any]) -> ComplaintInsight:
        category = context.get("category") or "General"
        intent = context.get("intent")
        sentiment = context.get("sentiment") or "Neutral"
        priority = context.get("priority") or "Medium"
        entities = context.get("entities") or {}
        play = PLAYBOOK.get(category, DEFAULT_PLAY)

        first = re.split(r"(?<=[.!?])\s+", complaint_text.strip())[0][:220]
        summary = f"Customer reports a {play['issue']}" + (f" ({intent.lower()})" if intent else "") + f": “{first}”"
        if sentiment in ("Very Negative", "Negative"):
            summary += f" The customer is {sentiment.lower()} and the case is {priority} priority."

        issues = [play["issue"].capitalize()]
        if entities.get("amounts"):
            issues.append(f"Amount involved: {entities['amounts'][0]['text']}")
        if entities.get("repeat_contact"):
            issues.append("Repeat contact — previous attempts did not resolve it")
        if sentiment == "Very Negative":
            issues.append("High customer frustration / churn risk")

        actions = list(play["actions"])
        if entities.get("repeat_contact") or priority in ("High", "Critical"):
            actions.insert(0, "Take ownership now and call the customer back within the hour")

        apology = "I'm sorry for the trouble" + (
            " and that you had to contact us more than once" if entities.get("repeat_contact") else ""
        )
        reply = (
            f"Hello,\n\n{apology}. I've reviewed your complaint about the {play['issue']} and I'm personally looking "
            f"into it now. I'll update you with the outcome and next steps shortly.\n\nRegards,\nShopzilla Support"
        )
        return ComplaintInsight(
            summary=summary, key_issues=issues[:4], recommended_actions=actions[:5], customer_reply=reply
        )


def get_provider() -> InsightProvider:
    s = get_settings()
    if s.llm_provider == "openai":
        if not s.openai_api_key:
            log.warning("LLM_PROVIDER=openai but OPENAI_API_KEY is empty; using the mock provider")
            return MockProvider()
        return OpenAIProvider(s.openai_api_key, s.openai_model)
    return MockProvider()


def generate_insight(
    text: str, context: dict[str, Any], known_names: list[str] | None = None
) -> tuple[ComplaintInsight, InsightProvider]:
    provider = get_provider()
    masked = mask_pii(text, known_names)
    try:
        return provider.generate(masked, context), provider
    except Exception:
        if provider.name == "mock":
            raise
        log.exception("OpenAI call failed; falling back to the mock provider")
        fallback = MockProvider()
        return fallback.generate(masked, context), fallback
