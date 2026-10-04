# AI-Powered Customer Complaint Intelligence System

**Python · scikit-learn · Hugging Face Transformers · OpenAI API · FastAPI · React**

An NLP pipeline classifies every customer complaint by **category, intent, sentiment and priority** for
automated triage; an LLM **summarises the complaint, extracts the key issues and recommends actions**; a React
dashboard tracks **trends, sentiment and high-priority issues**. Built on the Kaggle *eCommerce Customer Service
Satisfaction* dataset (85,907 support records from an Indian e-commerce company). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).


| Capability | How |
|---|---|
| Category (12 classes) & intent (57 sub-categories) | scikit-learn: TF-IDF (word + char n-grams) + structured fields → Logistic Regression, chosen against a text-only baseline on validation macro-F1 |
| Sentiment (5 levels) | Pretrained Hugging Face model `nlptown/bert-base-multilingual-uncased-sentiment`, validated against CSAT |
| Entities | Rules: ₹ amounts (₹/Rs/INR/lakh), order IDs, dates, products, repeat-contact cues |
| Priority (Low → Critical) | Transparent raise-only business rules ([docs/PRIORITY_RULES.md](docs/PRIORITY_RULES.md)) — never the LLM |
| Summary, key issues, recommended actions, draft reply | OpenAI API with structured outputs; offline **mock** provider when no key is set; PII masked first |
| Dashboard | KPIs, daily volume & sentiment trends, category / intent / channel breakdowns, week-over-week emerging issues, open high-priority list, auto-generated insights |

---

## Quick start (Windows PowerShell)

Prerequisites: Python 3.12, Node 20+, Docker Desktop, and the dataset CSV saved as `data\ecommerce_support.csv`.

```powershell
.\scripts\dev.ps1 setup     # .env, Python venv, pip + npm install
.\scripts\dev.ps1 up        # PostgreSQL 16 + pgvector (localhost:15432) and Redis (localhost:16379) in Docker
.\scripts\dev.ps1 migrate   # create the database and apply the Alembic migrations
.\scripts\dev.ps1 train     # data profile, train classifiers, validate the sentiment model (~45 min on CPU)
.\scripts\dev.ps1 import    # load the 85,907 historical complaints into Postgres (~75 s, idempotent)
.\scripts\dev.ps1 start     # API on http://localhost:18000, app on http://localhost:15173
```

Other commands: `.\scripts\dev.ps1 test` (needs `up`), `lint`, `api`, `web`, `down`, `reset-db`.

**End-to-end test:** `.\scripts\dev.ps1 e2e` runs a Playwright test of the whole flow (dashboard → new complaint →
Analyze → save → AI insights → list search → dashboard → resolve). It starts its own API and web servers on ports
18100/15200 with a separate Postgres database (`complaints_e2e`, wiped on every run) and the mock LLM, so it never
touches your data. It needs the trained
models; Chromium is downloaded into `.pw-browsers\` on first run. Ports live in `.env`
(`API_PORT`, `WEB_PORT`). To use OpenAI, set `LLM_PROVIDER=openai` and `OPENAI_API_KEY=...` in `.env` and restart
the API; each insight then shows its token count and estimated cost.

On macOS/Linux the same steps are: `python -m venv backend/.venv`, `pip install -r backend/requirements.txt -r
backend/requirements-dev.txt`, `python ml/train_classifiers.py`, `python ml/eval_sentiment.py`,
`docker compose up -d postgres redis`, `cd backend && python -m scripts.prepare_db && python -m scripts.import_dataset`, `uvicorn app.main:app --port 18000`, `cd frontend && npm i && npm run dev`.

## Using it

1. **Dashboard** — volume (per day, week or month), sentiment trend, top categories and intents, emerging issues
   (for example "Payments related complaints rose 56% this week") and the open high-priority list. Switch 7 / 30 / 90 days.
2. **New complaint** — paste a complaint and press **Analyze** to preview the AI triage (category, intent,
   sentiment, priority with the rules that fired, extracted entities), then **Save**.
   Try *Fill example*: "I was charged twice for my order of ₹12,500 and have already contacted support three
   times…" → Payments related · Very Negative · ₹12,500 · repeat contact → **Critical**.
3. **Complaint detail** — **Generate insights** for an LLM summary, key issues, recommended actions and a draft
   reply (copied by the agent, never sent automatically). Correct the category if the model was wrong — priority
   is recomputed by the rules. Change status Open → In Progress → Resolved.
4. **Complaints** — search and filter 85k+ complaints by status, category, sentiment, priority, source or
   "needs review".

## ML results

Real numbers from `.\scripts\dev.ps1 train` (details: [ml/MODEL_CARD.md](ml/MODEL_CARD.md),
[classifier report](ml/reports/classifier_report.md), [sentiment report](ml/reports/sentiment_report.md)).

**Category & intent** — held-out test set (4,312 remarks; 70/15/15 split, seed 42):

| Task | Model | Accuracy | Macro-F1 |
|---|---|---|---|
| Category (12) | majority-class baseline | 0.516 | 0.057 |
| Category (12) | TF-IDF + LR, text only (validation) | 0.526 | 0.097 |
| Category (12) | **TF-IDF + structured fields + LR** | **0.529** | **0.102** |
| Intent (57) | majority-class baseline | 0.261 | 0.008 |
| Intent (57) | **TF-IDF + structured fields + LR** | **0.274** | **0.040** |

On **38 realistic hand-written complaints** the deployed category pipeline (model + domain keyword prior) is
**95% accurate** (model alone: 42%). The keyword prior also raised validation macro-F1 from 0.105 to 0.121.

**Sentiment** — `nlptown/bert-base-multilingual-uncased-sentiment` vs the customer's CSAT on 28,742 remarks:
Spearman **0.52**, within ±1 star **72.8%**, and it flags **78%** of dissatisfied customers (CSAT ≤ 2).
Mean CSAT rises monotonically from 2.75 (Very Negative) to 4.70 (Very Positive).

> Why category scores are low on the dataset: its only text is the customer's post-contact survey remark
> (median 3 words, mostly "good", "thank you"), which rarely says what the problem was. The baseline row and the
> realistic-complaint set are shown so the numbers can be read honestly.

## API

All routes live under `/api/v1/` (spec's API table).

| Method | Path | Purpose |
|---|---|---|
| POST | `/ai/analyze` | Run the NLP triage pipeline on a text without saving |
| POST | `/tickets` | Create a ticket (`INC-00001` …); triage runs automatically and is recorded in `ai_analyses` |
| GET | `/tickets` | List with `q`, `status`, `category`, `sentiment`, `priority`, `channel`, `source`, `needs_review`, `sort`, `page` |
| GET / PATCH | `/tickets/{id}` | Detail · update `status` or correct `category` |
| POST | `/ai/draft-response` | Copilot for `{ticket_id}`: LLM summary, key issues, recommended actions, draft reply |
| GET | `/analytics/overview`, `/trends?granularity=day\|week\|month`, `/categories`, `/emerging` | Dashboard analytics (Redis-cached) |
| GET | `/health`, `/categories` | Model versions in use · category list |

Interactive docs: http://localhost:18000/docs

## Project layout

```
backend/app/        FastAPI app — api/ (routes), services/ (complaints, dashboard SQL), ai/ (triage, classifier,
                    sentiment, entities, priority, pii, llm), models.py, schemas.py
backend/scripts/    prepare_db.py (create + migrate), import_dataset.py
backend/migrations/ Alembic migrations
ml/                 profile_dataset.py, train_classifiers.py, eval_sentiment.py, reports/, MODEL_CARD.md
frontend/src/       pages/ (Dashboard, Complaints, NewComplaint, ComplaintDetail), components/, api/
tests/backend/      pytest (AI components, API, dashboard)
tests/e2e/          Playwright end-to-end test of the full complaint flow
docs/               DATA_PROFILE.md, ARCHITECTURE.md, PRIORITY_RULES.md
scripts/dev.ps1     all developer commands
```

## Design decisions

- **AI where language matters, rules where decisions matter.** Models read the text; priority is an
  explainable rule set (the data has no priority labels).
- **Honest evaluation.** The dataset's only text is a short post-contact survey remark (median 3 words, mostly
  "good" / "thank you"), so dataset macro-F1 is low for any model. Reports show the majority baseline, and a
  fixed set of realistic complaints measures the deployed pipeline on complaint-style text.
- **Human in the loop.** Low-confidence predictions are flagged *needs review*; the LLM's reply is only a draft.
- **Privacy.** Emails, phones, cards, Aadhaar, PAN, UPI IDs and names are masked before any LLM call.
- **Simple to run.** Docker Compose for Postgres + Redis, one FastAPI process, Vite; the mock LLM means everything works without an API key.

## Known limitations

- **Training text is weak.** Dataset remarks are survey feedback, not complaint descriptions, so the
  classifiers learn little from them; the keyword prior carries much of the accuracy on real complaint text.
  Rare intents (most of the 57) are effectively never predicted.
- **Historical labels.** Imported complaints keep the dataset's own category/intent; only new complaints are
  model-labelled. 67% of imported rows have no remark, so they have a templated text and no sentiment.
- **Dates are shifted.** Imported timestamps are moved forward by whole days so the newest record is yesterday
  (relative spacing preserved; disable with `import_dataset --no-shift`). The data covers only ~5 weeks.
- **LLM.** The mock is the default; with `LLM_PROVIDER=openai` real calls were verified end to end
  (`gpt-4o-mini`, ~470 tokens and ~$0.00014 per complaint at list price). Failures are never replaced by mock
  output: a bad key, rate limit/quota, timeout or network error shows a clear message in the UI. Masked
  placeholders such as `[NAME]` can appear in the generated summary and draft reply for the agent to fill in.
- **Sentiment model speed.** BERT on CPU scores ~15 remarks/s in batch; single complaints take ~0.1–0.3 s.
- **No authentication or multi-user features.** This is a single-user analysis tool; put it behind your own
  auth before exposing it beyond localhost.
