"""LLM copilot: summary, likely root cause, key issues, recommended next steps and a draft reply.

* LLM_PROVIDER=openai uses the OpenAI API with structured outputs (the response is parsed into
  the `ComplaintInsight` schema, so it is always valid JSON with the right fields).
* LLM_PROVIDER=mock (default) produces realistic, deterministic output offline — no key needed.

Personal data is masked before the text leaves the process (the complaint and the conversation so far). The reply
is only a draft: an agent must review, optionally edit, and accept it — nothing is ever sent automatically.

OpenAI failures are never hidden behind mock output: each one is raised as an `LLMError` with an
HTTP status and a message the UI shows as-is (bad key, rate limit / quota, timeout, network, ...).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.ai.pii import CUSTOMER, mask_pii
from app.core.config import get_settings

log = logging.getLogger(__name__)

PROMPT_VERSION = "copilot-v3"

SYSTEM_PROMPT = """You are a senior customer-support analyst for Shopzilla, an Indian e-commerce company.
Given one customer complaint, its automated triage, the conversation on the ticket so far and reference material
(help articles [A1].. and similar past tickets [T1]..), produce:
- summary: 1-2 sentences, neutral, factual.
- root_cause: the most likely underlying cause in one sentence, phrased as a hypothesis the agent should verify
  ("Likely ..."). If the complaint does not support a cause, say "Unclear from the complaint" and what to check.
- key_issues: 1-4 short noun phrases naming the concrete problems.
- recommended_actions: 2-5 imperative, specific next steps for the support agent (check systems, refund, escalate...).
- customer_reply: a short, empathetic draft reply the agent can edit. Do not promise anything you cannot verify;
  never invent order details, amounts, dates or reference numbers that are not in the complaint or conversation.
The conversation is the support team's notes and replies so far. Treat what it reports as established facts: never
recommend a check it says was already done — recommend the step that follows from its result — and let those facts
shape the root cause and the reply.
Ground your answer in the references: follow the policies and timelines in the help articles, and use similar
past tickets to see what the problem usually turns out to be. Only state policy facts (timelines, amounts, limits) that
appear in a help article. List in references_used the ids (e.g. "A1", "T2") of the references you actually relied on;
leave it empty if none was relevant. Never mention reference ids, other tickets or other customers in customer_reply.
Placeholders like [EMAIL] or [PHONE] are masked personal data; keep them as-is. [CUSTOMER] stands for this
customer's name: greet them with it in customer_reply."""


class ComplaintInsight(BaseModel):
    summary: str = Field(description="1-2 sentence neutral summary")
    root_cause: str = Field(description="Most likely underlying cause, phrased as a hypothesis to verify")
    key_issues: list[str] = Field(min_length=1, max_length=4)
    recommended_actions: list[str] = Field(min_length=1, max_length=5)
    customer_reply: str
    references_used: list[str] = Field(description='Ids of the references relied on, e.g. ["A1", "T2"]; may be empty')


Usage = dict[str, Any]


class LLMError(Exception):
    """An LLM call failed in a way the user should be told about (mapped to an HTTP response)."""

    def __init__(self, code: str, message: str, status: int = 502, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retry_after = retry_after


@dataclass
class InsightRun:
    insight: ComplaintInsight
    provider: str
    model: str
    usage: Usage | None  # tokens + estimated cost (None for the mock)


class InsightProvider(Protocol):
    name: str
    model: str

    def generate(self, complaint_text: str, context: dict[str, Any]) -> tuple[ComplaintInsight, Usage | None]: ...


def build_user_prompt(masked_text: str, context: dict[str, Any]) -> str:
    lines = [f"Complaint: {masked_text}"]
    for key in ("category", "intent", "sentiment", "priority", "channel", "product", "amount_inr"):
        if context.get(key) not in (None, ""):
            lines.append(f"{key.replace('_', ' ').title()}: {context[key]}")
    conversation = context.get("conversation") or []
    if conversation:
        lines.append("Conversation so far (oldest first):")
        lines.extend(f"- {c['author']}: {c['body']}" for c in conversation)
    references = context.get("references") or []
    if references:
        lines.append("References:")
        for r in references:
            lines.append(f"[{r['ref']}] {r['heading']}")
            lines.append(f"    {r['text']}")
    return "\n".join(lines)


class OpenAIProvider:
    name = "openai"

    def __init__(
        self, api_key: str, model: str, *, timeout: float = 30.0, max_retries: int = 1, base_url: str | None = None
    ) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries, base_url=base_url or None)
        self.model = model
        self.timeout = timeout

    def generate(self, complaint_text: str, context: dict[str, Any]) -> tuple[ComplaintInsight, Usage | None]:
        import openai

        started = time.perf_counter()
        try:
            completion = self.client.chat.completions.parse(
                model=self.model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(complaint_text, context)},
                ],
                response_format=ComplaintInsight,
            )
        except openai.OpenAIError as exc:
            raise map_openai_error(exc, model=self.model, timeout=self.timeout) from exc
        except ValidationError as exc:  # a compatible endpoint returned JSON that doesn't match the schema
            raise LLMError(
                "llm_invalid_output", "The model returned a malformed copilot answer (missing fields). Try again.", 502
            ) from exc
        message = completion.choices[0].message
        if message.parsed is None:
            reason = getattr(message, "refusal", None) or "no structured content returned"
            raise LLMError("llm_refused", f"OpenAI did not return a copilot answer: {reason}", 502)
        usage = usage_from(completion, time.perf_counter() - started)
        log.info("openai copilot call %s", usage)
        return message.parsed, usage


def usage_from(completion: Any, seconds: float) -> Usage | None:
    u = getattr(completion, "usage", None)
    if u is None:
        return None
    s = get_settings()
    cost = (u.prompt_tokens * s.openai_input_usd_per_1m + u.completion_tokens * s.openai_output_usd_per_1m) / 1e6
    return {
        "model": getattr(completion, "model", None),
        "prompt_tokens": u.prompt_tokens,
        "completion_tokens": u.completion_tokens,
        "total_tokens": u.total_tokens,
        "estimated_cost_usd": round(cost, 6),
        "latency_s": round(seconds, 2),
    }


def map_openai_error(exc: Exception, *, model: str, timeout: float) -> LLMError:
    """Translate OpenAI SDK exceptions into messages a support agent can act on."""
    import openai

    if isinstance(exc, openai.AuthenticationError):
        return LLMError(
            "llm_auth_failed", "OpenAI rejected the API key. Check OPENAI_API_KEY in .env and restart the backend.", 502
        )
    if isinstance(exc, openai.PermissionDeniedError):
        return LLMError("llm_forbidden", f"The API key is not allowed to use model '{model}'.", 502)
    if isinstance(exc, openai.NotFoundError):
        return LLMError(
            "llm_model_not_found", f"OpenAI model '{model}' was not found. Check OPENAI_MODEL in .env.", 502
        )
    if isinstance(exc, openai.RateLimitError):
        body = getattr(exc, "body", None)
        code = body.get("code") if isinstance(body, dict) else None
        if code == "insufficient_quota":
            return LLMError(
                "llm_quota_exceeded",
                "OpenAI quota exhausted for this API key. Check the account's billing and usage limits.",
                429,
            )
        retry = _retry_after(exc)
        wait = f"in about {retry} s" if retry else "in a moment"
        return LLMError("llm_rate_limited", f"OpenAI rate limit reached. Try again {wait}.", 429, retry_after=retry)
    if isinstance(exc, openai.APITimeoutError):
        return LLMError("llm_timeout", f"OpenAI did not respond within {timeout:g} s. Try again.", 504)
    if isinstance(exc, openai.APIConnectionError):
        return LLMError("llm_unreachable", "Could not reach the OpenAI API. Check the network connection.", 502)
    if isinstance(exc, openai.LengthFinishReasonError | openai.ContentFilterFinishReasonError):
        return LLMError("llm_incomplete", "OpenAI stopped before finishing the copilot answer. Try again.", 502)
    if isinstance(exc, openai.APIStatusError):
        return LLMError(
            "llm_upstream_error", f"OpenAI returned an error (HTTP {exc.status_code}). Try again later.", 502
        )
    return LLMError("llm_error", "The copilot request to OpenAI failed. Try again.", 502)


def _retry_after(exc: Any) -> int | None:
    response = getattr(exc, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    try:
        return max(1, round(float(value))) if value else None
    except ValueError:
        return None


# ----------------------------------------------------------------------------------- mock
PLAYBOOK: dict[str, dict[str, Any]] = {
    "Payments related": {
        "issue": "payment problem",
        "cause": (
            "Likely a duplicate capture at the payment gateway, or a debit whose order confirmation failed — "
            "verify the number of successful transactions for the order."
        ),
        "actions": [
            "Check the payment gateway logs for the order and confirm how many successful debits exist",
            "If a duplicate debit is confirmed, raise a reversal for the extra amount",
            "Share the refund reference number and expected timeline (5–7 business days) with the customer",
        ],
    },
    "Refund Related": {
        "issue": "refund not received",
        "cause": (
            "Likely the refund was initiated but is still in the bank's settlement window, or it failed and was "
            "never re-triggered — check the refund status and reference."
        ),
        "actions": [
            "Look up the refund status and reference number for the order",
            "If the refund is past its SLA, escalate to the finance team with the transaction details",
            "Give the customer the refund reference and the bank's expected credit date",
        ],
    },
    "Returns": {
        "issue": "return / pickup problem",
        "cause": (
            "Likely a missed or unassigned reverse-pickup slot with the logistics partner — check the pickup "
            "attempts on the return request."
        ),
        "actions": [
            "Verify the return request status and pickup slot in the logistics system",
            "Reschedule the reverse pickup or arrange a self-ship option",
            "Confirm the refund or replacement will start once the item is picked up",
        ],
    },
    "Order Related": {
        "issue": "order delivery problem",
        "cause": (
            "Likely a courier delay or a shipment stuck at a hub — check the last tracking scan against the "
            "promised date."
        ),
        "actions": [
            "Check the shipment tracking and the last courier scan",
            "Contact the courier partner for an updated delivery date",
            "Offer cancellation with a full refund if the delay exceeds the promised date",
        ],
    },
    "Cancellation": {
        "issue": "cancellation request",
        "cause": (
            "Likely the order moved past the cancellable stage before the request was processed — check the "
            "shipment status at the time of the request."
        ),
        "actions": [
            "Check whether the order has already shipped",
            "Cancel the order or initiate return-to-origin if it is in transit",
            "Confirm the refund timeline for prepaid orders",
        ],
    },
    "Product Queries": {
        "issue": "product question",
        "cause": "Likely missing or unclear information on the product page — check the listing and warranty terms.",
        "actions": [
            "Answer from the product specification and warranty terms",
            "Share the nearest authorised service centre if needed",
        ],
    },
    "Feedback": {
        "issue": "service quality feedback",
        "cause": (
            "Likely an earlier support interaction that fell short of expectations — review the customer's recent"
            " contacts."
        ),
        "actions": [
            "Acknowledge the feedback and apologise for the experience",
            "Log the interaction for quality review with the team lead",
        ],
    },
    "Offers & Cashback": {
        "issue": "cashback / offer not applied",
        "cause": (
            "Likely the order did not meet an offer condition (payment method, minimum value or validity) or the "
            "cashback job has not run yet."
        ),
        "actions": [
            "Verify the offer terms and the customer's eligibility",
            "Credit the cashback manually if the order qualified",
        ],
    },
}
DEFAULT_PLAY = {
    "issue": "customer issue",
    "cause": "Unclear from the complaint — review the customer's order and account history to find the cause.",
    "actions": ["Review the customer's order and account history", "Resolve or route to the right specialist team"],
}


class MockProvider:
    """Deterministic, offline stand-in that builds realistic output from the triage results."""

    name = "mock"
    model = "mock-copilot-v3"

    def generate(self, complaint_text: str, context: dict[str, Any]) -> tuple[ComplaintInsight, Usage | None]:
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
        conversation = context.get("conversation") or []
        if conversation:
            actions.insert(0, f"Follow up on the latest note from {conversation[-1]['author']} before replying")
        references = context.get("references") or []
        articles = [r for r in references if r["type"] == "article"]
        tickets = [r for r in references if r["type"] == "ticket"]
        used = []
        if articles:  # grounded: follow the most relevant help article
            actions.insert(1 if len(actions) > 1 else 0, f"Follow the help article “{articles[0]['title']}”")
            used.append(articles[0]["ref"])
        if tickets:
            used.append(tickets[0]["ref"])

        apology = "I'm sorry for the trouble" + (
            " and that you had to contact us more than once" if entities.get("repeat_contact") else ""
        )
        greeting = f"Hello {CUSTOMER}," if context.get("customer_known") else "Hello,"
        reply = (
            f"{greeting}\n\n{apology}. I've reviewed your complaint about the {play['issue']} and I'm personally "
            "looking into it now. I'll update you with the outcome and next steps shortly.\n\n"
            "Regards,\nShopzilla Support"
        )
        insight = ComplaintInsight(
            summary=summary,
            root_cause=play["cause"],
            key_issues=issues[:4],
            recommended_actions=actions[:5],
            customer_reply=reply,
            references_used=used,
        )
        return insight, None


def get_provider() -> InsightProvider:
    s = get_settings()
    if s.llm_provider == "openai":
        if not s.openai_api_key:
            raise LLMError("llm_not_configured", "LLM_PROVIDER is 'openai' but OPENAI_API_KEY is empty in .env.", 503)
        return OpenAIProvider(
            s.openai_api_key,
            s.openai_model,
            timeout=s.openai_timeout_seconds,
            max_retries=s.openai_max_retries,
            base_url=s.openai_base_url,
        )
    return MockProvider()


def restore_customer(insight: ComplaintInsight, customer_name: str | None) -> ComplaintInsight:
    """Put the customer's first name back where the model used [CUSTOMER] — locally, after the call, so the name
    itself never reaches the LLM. Without a known name the greeting falls back to a neutral word."""
    first = (customer_name or "").strip().split(" ")[0] or "there"

    def fix(text: str) -> str:
        return text.replace(CUSTOMER, first)

    return insight.model_copy(
        update={
            "summary": fix(insight.summary),
            "root_cause": fix(insight.root_cause),
            "key_issues": [fix(k) for k in insight.key_issues],
            "recommended_actions": [fix(a) for a in insight.recommended_actions],
            "customer_reply": fix(insight.customer_reply),
        }
    )


def generate_insight(
    text: str, context: dict[str, Any], known_names: list[str] | None = None, customer_name: str | None = None
) -> InsightRun:
    """Mask personal data (complaint, conversation and references), ask the configured provider, then restore the
    customer's name in its answer. Errors propagate as LLMError."""
    provider = get_provider()

    def mask(value: str) -> str:
        return mask_pii(value, known_names, customer_name)

    masked = mask(text)
    context = {**context, "customer_known": bool(customer_name)}
    if context.get("conversation"):
        context["conversation"] = [{**c, "body": mask(c["body"])} for c in context["conversation"]]
    if context.get("references"):  # other customers' tickets: masked like everything else
        context["references"] = [{**r, "text": mask(r["text"])} for r in context["references"]]
    insight, usage = provider.generate(masked, context)
    return InsightRun(
        insight=restore_customer(insight, customer_name), provider=provider.name, model=provider.model, usage=usage
    )
