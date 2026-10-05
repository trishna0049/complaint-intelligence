# Model card — complaint triage (`triage-v1`)

## What it does

Given a complaint's text (plus channel, product, amount and whether an order ID is present) it predicts:

| Output | Model | Artifact |
|---|---|---|
| Category (12 classes) | scikit-learn Logistic Regression on TF-IDF word 1–2-grams + char 2–5-grams + one-hot structured fields, blended with a domain keyword prior | `ml/artifacts/category_model.joblib` |
| Intent (57 sub-categories) | Same architecture; restricted to intents observed under the predicted category | `ml/artifacts/intent_model.joblib` |
| Sentiment (5 levels) | Pretrained `nlptown/bert-base-multilingual-uncased-sentiment` (1–5 stars), not fine-tuned | Hugging Face hub |

Priority is **not** a model — it is rule-based (`docs/PRIORITY_RULES.md`). Summaries and recommendations come
from an LLM at request time and are not part of this card.

## Training data

Kaggle *eCommerce Customer Service Satisfaction* — 85,907 support records (Aug 2023, Indian e-commerce).
Only the **28,742 rows with a real `Customer Remarks` value** are used; rows with empty remarks are excluded
because their in-app description is a template that contains the label. Split 70/15/15 stratified by
category, seed 42. Model selection on validation; one final score on the untouched test set.

## Results (held-out test set, 4,312 rows)

| Task | Model | Accuracy | Macro-F1 | Weighted-F1 |
|---|---|---|---|---|
| Category | text + structured LR | **0.529** | **0.102** | 0.448 |
| Category | majority class baseline | 0.516 | 0.057 | 0.352 |
| Category | + keyword prior (deployed) | 0.502 | 0.105 | 0.440 |
| Intent | text + structured LR | **0.274** | **0.040** | 0.194 |
| Intent | majority class baseline | 0.261 | 0.008 | 0.108 |

Validation macro-F1 for the category model: 0.097 (text-only baseline) → 0.105 (text + structured) → 0.121
(with keyword prior). Class-balanced variants scored within 0.005 macro-F1 but lost 30+ points of accuracy and
were rejected by the documented tie-break.

**Realistic complaint text** — 38 hand-written complaints (`ml/data/fixed_complaints.csv`):
model alone **42%**, deployed pipeline (model + keyword prior) **95%** category accuracy.

Full per-class precision/recall/F1 and the confusion matrix: `ml/reports/classifier_report.md`,
`ml/reports/category_confusion.png`.

## Sentiment validation

Validated against the customer's own CSAT score (1–5) on all 28,742 remarks
(`ml/reports/sentiment_report.md`, `ml/reports/sentiment_vs_csat.png`):

| Metric | Value |
|---|---|
| Spearman correlation (expected stars vs CSAT) | **0.520** |
| Exact match / within ±1 star | 44.2% / 72.8% |
| Dissatisfied customers (CSAT ≤ 2) detected — precision / recall / F1 | 0.514 / **0.776** / 0.619 |
| Mean CSAT for predicted Very Negative → Very Positive | 2.75 → 3.26 → 4.26 → 4.68 → 4.70 (monotonic) |

Exact match is below the "always predict CSAT 5" reference (68.4%) because CSAT is skewed to 5 and rates the
whole interaction, while the model reads only the words; the monotonic rise in mean CSAT and the 78% recall on
unhappy customers are the useful signals for triage.

## Intended use and limitations

- **Assistive triage.** Predictions under 45% category confidence are flagged *needs review*; agents can
  correct the category in one click.
- **Weak training text.** Dataset remarks are post-contact survey comments (median 3 words; "good", "thank
  you"), so dataset scores are low for any model and mostly reflect the class prior. The keyword prior and the
  fixed realistic set exist because real complaints contain the domain vocabulary the remarks lack.
- **Long-tail intents.** Many of the 57 sub-categories have under 50 examples with text; rare intents are
  effectively never predicted.
- **Language.** English / Hinglish remarks only; no evaluation on other Indian languages.
- **Not for automated decisions about customers.** Outputs route and prioritise work for humans.

## Reproduce

```powershell
.\scripts\dev.ps1 train
```

## Retrieval embeddings (similar tickets, knowledge base, RAG)

- **Model:** `sentence-transformers/all-MiniLM-L6-v2` (pretrained, not fine-tuned), 384 dimensions, L2-normalised,
  CPU (~1,000 texts/s). Vectors live in pgvector with HNSW cosine indexes; each row records the model name so a
  model change can never mix vectors.
- **What is embedded:** tickets with real complaint text — everything typed in the app plus dataset remarks of at
  least four words (13,779 of 85,907 rows; templated descriptions and one-word survey remarks are skipped) — and every
  help article (title + body).
- **Search:** hybrid — vector neighbours + PostgreSQL full text, fused by weighted Reciprocal Rank Fusion (k=60,
  keyword weight 0.3). Vector matches below 0.35 (tickets) / 0.20 (articles) cosine are dropped.
- **Evaluation** on fixed examples ([reports/retrieval_report.md](reports/retrieval_report.md)): 30 customer-style
  knowledge-base queries — hybrid recall@1 0.93, recall@3 1.00, MRR 0.96 (meaning only 0.90 / 0.97 / 0.93, keywords
  only 0.77 / 0.87 / 0.82); in 8 of 8 ticket triples the paraphrase is closer than a different problem. The fusion
  weight and thresholds were chosen on these same 30 queries, so the hybrid numbers are optimistic.
- **Limits:** English-centric (Hinglish and heavy typos degrade matches); the dataset's remarks are post-contact survey
  comments, so "similar historical tickets" are often feedback about a similar problem rather than full complaints.
- **Fallback:** when the model can't load (or in unit tests) a deterministic hashing embedder keeps search working
  on keyword overlap.
