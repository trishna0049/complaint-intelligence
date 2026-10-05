"""Unit tests for the rule-based and pure parts of the AI pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from app.ai.entities import extract_entities
from app.ai.keywords import blend_with_prior
from app.ai.llm import ComplaintInsight, MockProvider, build_user_prompt, generate_insight
from app.ai.pii import mask_pii
from app.ai.priority import LEVELS, decide_priority
from app.ai.sentiment import LexiconSentiment

# ---------------------------------------------------------------- priority rules


def test_spec_example_is_critical():
    d = decide_priority("Payments related", "Very Negative", 12500, repeat_contact=True)
    assert d.priority == "Critical"
    assert d.base == "High"
    assert [r["rule"] for r in d.reasons] == ["R1", "R3", "R5"]  # all signals recorded
    assert d.reasons[0]["to"] == "Critical" and d.reasons[1]["from"] == d.reasons[1]["to"] == "Critical"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"category": "Feedback"}, "Low"),
        ({"category": "Feedback", "sentiment": "Negative"}, "Medium"),
        ({"category": "Feedback", "amount_inr": 15000}, "Medium"),
        ({"category": "Feedback", "amount_inr": 75000}, "High"),
        ({"category": "Returns", "repeat_contact": True}, "High"),
        ({"category": "Feedback", "intent": "Fraudulent User"}, "High"),
        ({"category": "Others", "text": "I will file a consumer court case"}, "High"),
        ({"category": "Unknown thing"}, "Medium"),
    ],
)
def test_priority_rules(kwargs, expected):
    assert decide_priority(**kwargs).priority == expected


def test_priority_rules_only_raise():
    for category in ("Feedback", "Returns", "Payments related"):
        base = decide_priority(category).priority
        for sentiment in (None, "Very Negative", "Negative", "Neutral", "Positive", "Very Positive"):
            for amount in (None, 100, 20000, 90000):
                for repeat in (False, True):
                    d = decide_priority(category, sentiment, amount, repeat)
                    assert LEVELS.index(d.priority) >= LEVELS.index(base)
                    assert all(LEVELS.index(r["to"]) >= LEVELS.index(r["from"]) for r in d.reasons)


# ---------------------------------------------------------------- entities (fixed examples)


def test_amounts_in_many_formats():
    e = extract_entities("Charged ₹12,500 then Rs. 499 and INR 2,000; also 1.5 lakh rupees")
    values = sorted(a["value"] for a in e["amounts"])
    assert values == [499, 2000, 12500, 150000]
    assert e["max_amount_inr"] == 150000


def test_order_ids_dates_products_repeat():
    e = extract_entities("Order OD123456789 for my iPhone placed on 12/08/2023 — I have called three times already.")
    assert e["order_ids"] == ["OD123456789"]
    assert "12/08/2023" in e["dates"]
    assert e["products"] == ["Mobile"]
    assert e["repeat_contact"] is True


def test_no_entities_in_plain_text():
    e = extract_entities("Thank you, very good service")
    assert e["amounts"] == [] and e["order_ids"] == [] and e["repeat_contact"] is False


# ---------------------------------------------------------------- PII masking


def test_pii_is_masked():
    text = (
        "My name is Ravi Kumar, email ravi.k@gmail.com, phone +91 98765 43210, card 4111 1111 1111 1111, "
        "PAN ABCDE1234F, UPI ravi@okaxis. Order OD123456789 for ₹12,500."
    )
    masked = mask_pii(text)
    for secret in ("ravi.k@gmail.com", "98765 43210", "4111 1111 1111 1111", "ABCDE1234F", "Ravi Kumar"):
        assert secret not in masked
    assert "[EMAIL]" in masked and "[PHONE]" in masked and "[CARD]" in masked and "[PAN]" in masked
    # Order IDs and amounts are kept — they are needed and not personal.
    assert "OD123456789" in masked and "₹12,500" in masked


def test_known_customer_name_is_masked():
    assert mask_pii("Priya Sharma here, refund please", known_names=["Priya Sharma"]) == "[NAME] here, refund please"
    # A known name's parts are masked on their own too, as whole words only.
    assert (
        mask_pii("Thanks, Meera. Iyer family order", known_names=["Meera Iyer"])
        == "Thanks, [NAME]. [NAME] family order"
    )
    assert mask_pii("Ravindra called", known_names=["Ravi Kumar"]) == "Ravindra called"


# ---------------------------------------------------------------- LLM (mock) + keyword prior


def test_mock_insight_matches_schema_and_uses_triage():
    ctx = {
        "category": "Payments related",
        "intent": "Online Payment Issues",
        "sentiment": "Very Negative",
        "priority": "Critical",
        "entities": extract_entities("charged twice ₹12,500, contacted three times"),
    }
    out, usage = MockProvider().generate("I was charged twice for ₹12,500.", ctx)
    assert isinstance(out, ComplaintInsight)
    assert usage is None  # the mock costs nothing
    assert "payment" in out.summary.lower()
    assert any("₹12,500" in i for i in out.key_issues)
    assert 2 <= len(out.recommended_actions) <= 5


def test_generate_insight_masks_pii_before_provider(monkeypatch):
    seen = {}

    class Spy(MockProvider):
        def generate(self, complaint_text, context):
            seen["text"] = complaint_text
            return super().generate(complaint_text, context)

    monkeypatch.setattr("app.ai.llm.get_provider", lambda: Spy())
    generate_insight("Call me on 9876543210 or mail a@b.com", {"category": "Refund Related"})
    assert "9876543210" not in seen["text"] and "a@b.com" not in seen["text"]


def test_user_prompt_contains_triage_context():
    p = build_user_prompt("text", {"category": "Returns", "priority": "High", "product": None})
    assert "Category: Returns" in p and "Priority: High" in p and "Product" not in p


def test_keyword_prior_moves_probability_only_when_keywords_hit():
    classes = ["Payments related", "Returns"]
    proba = np.array([[0.2, 0.8], [0.2, 0.8]])
    out = blend_with_prior(["I was charged twice", "hello there"], proba, classes)
    assert out[0].argmax() == 0  # keyword "charged twice" -> Payments
    assert np.allclose(out[1], proba[1])  # no keywords -> unchanged
    assert np.allclose(out.sum(axis=1), 1)


def test_lexicon_fallback_sentiment():
    s = LexiconSentiment()
    assert s.predict("Worst service, totally frustrated").label in ("Very Negative", "Negative")
    assert s.predict("Good service, thank you").label in ("Positive", "Very Positive")
