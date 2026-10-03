# Priority rules

The dataset has **no priority labels**, so priority cannot be learned. It is decided by transparent business
rules in [`backend/app/ai/priority.py`](../backend/app/ai/priority.py) — never by the LLM — and every
complaint stores the list of rules that fired so the UI can explain *why* it got its priority.

## How it works

1. Start from the **base priority** of the complaint's category.
2. Apply the rules below in order. **A rule can only raise priority, never lower it.** The result is capped at
   Critical. Every rule that matches is recorded (also when the priority is already at or above its effect), so
   the explanation shows all the signals found.

Levels: `Low < Medium < High < Critical`

## Base priority by category

| Category | Base | Why |
|---|---|---|
| Payments related | High | Money has left the customer's account |
| Refund Related | High | Money owed to the customer |
| Returns, Order Related, Cancellation, Shopzilla Related, App/website | Medium | Service failure, no money lost yet |
| Product Queries, Feedback, Offers & Cashback, Onboarding related, Others | Low | Information requests and feedback |

## Raise-only rules

| Rule | Condition | Effect |
|---|---|---|
| R1 | Sentiment is **Very Negative** | +1 level |
| R2 | Sentiment is **Negative** | at least Medium |
| R3 | Amount ≥ ₹10,000 (from the form or extracted from the text) | +1 level |
| R4 | Amount ≥ ₹50,000 | at least High |
| R5 | Repeat contact ("already contacted", "three times", "again"…) | +1 level |
| R6 | Fraud / security signal (intent *Fraudulent User*, "fraud", "unauthorised", "hacked"…) | at least High |
| R7 | Legal threat ("consumer court", "legal notice", "lawyer"…) | at least High |

## Worked example

> "I was charged twice for my order of ₹12,500 and have already contacted support three times."

| Step | Priority |
|---|---|
| Base — Payments related | High |
| R1 Very Negative sentiment | **Critical** |
| R3 amount ₹12,500 ≥ ₹10,000 | Critical (capped) |
| R5 repeat contact | Critical (capped) |

## Tests

`tests/backend/test_ai_components.py` checks the worked example, every rule, and a property test that, for
every combination of category, sentiment, amount and repeat contact, the result is never below the base and
every recorded step goes up.
