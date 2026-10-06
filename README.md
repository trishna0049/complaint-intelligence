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
| Routing (team + agent) | Deterministic rules: category → owning team → least-busy agent; low confidence → review queue ([docs/ROUTING_RULES.md](docs/ROUTING_RULES.md)) |
| Similar tickets & knowledge base | MiniLM (`all-MiniLM-L6-v2`, 384 dims) on pgvector HNSW **+** PostgreSQL full text, fused by weighted Reciprocal Rank Fusion; 26 seeded help articles; evaluated on fixed examples ([ml/reports/retrieval_report.md](ml/reports/retrieval_report.md)) |
| Copilot: summary, likely root cause, key issues, next steps, draft reply | OpenAI API with structured outputs (prompt `copilot-v3`), **grounded (RAG)** in the most relevant help articles and similar past tickets plus the ticket's conversation, citing what it used; offline **mock** provider when no key is set; PII masked first (the customer's name is restored locally in the reply); the draft is only posted when an agent accepts it |
| SLA engine | Policies per priority (+ category), clock from creation, pause while waiting on the customer, warning at 80 % and breach at 100 % once each, automatic escalation, live countdown ([docs/SLA.md](docs/SLA.md)) |
| Notifications | Notification worker → table → Redis pub/sub → Server-Sent Events: bell, toasts, Notifications page; optional SMTP e-mail (Mailpit locally) ([docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md)) |
| Events | Transactional outbox → Kafka (KRaft) → AI, LLM, SLA and notification workers; idempotent consumers, 3 retries, dead-letter queue with Admin replay ([docs/EVENTS.md](docs/EVENTS.md)) |
| Dashboard | KPIs, daily volume & sentiment trends, category / intent / channel breakdowns, week-over-week emerging issues, open high-priority list, auto-generated insights |

---

## Quick start (Windows PowerShell)

Prerequisites: Python 3.12, Node 20+, Docker Desktop, and the dataset CSV saved as `data\ecommerce_support.csv`.

```powershell
.\scripts\dev.ps1 setup     # .env, Python venv, pip + npm install
.\scripts\dev.ps1 up        # PostgreSQL 16 + pgvector (:15432), Redis (:16379), Kafka KRaft (:19092), Kafka UI (:18090)
.\scripts\dev.ps1 migrate   # create the database and apply the Alembic migrations
.\scripts\dev.ps1 seed      # departments, teams, categories, admin, 1,371 dataset agents, knowledge base (~1 min)
.\scripts\dev.ps1 train     # data profile, train classifiers, validate the sentiment model (~45 min on CPU)
.\scripts\dev.ps1 import    # load the 85,907 historical complaints into Postgres (~75 s, idempotent)
.\scripts\dev.ps1 embed     # MiniLM embeddings of the 13,779 informative tickets (~2 min, idempotent)
.\scripts\dev.ps1 start     # Kafka topics, then API (:18000), workers and app (http://localhost:15173)
```

Other commands: `.\scripts\dev.ps1 test` (needs `up`), `lint`, `api`, `web`, `down`, `reset-db`.

**End-to-end test:** `.\scripts\dev.ps1 e2e` runs a Playwright test of the whole flow (dashboard → new complaint →
Analyze → save → routing → copilot → edit + accept the draft → list search → dashboard → reassign → start → comment +
attachment → resolve → close → timeline). It starts its own API and web servers on ports
18100/15200 with a separate Postgres database (`complaints_e2e`, wiped on every run) and the mock LLM, so it never
touches your data. It needs the trained
models; Chromium is downloaded into `.pw-browsers\` on first run. Ports live in `.env`
(`API_PORT`, `WEB_PORT`). To use OpenAI, set `LLM_PROVIDER=openai` and `OPENAI_API_KEY=...` in `.env` and restart
the API; each copilot run then shows its token count and estimated cost.

On macOS/Linux the same steps are: `python -m venv backend/.venv`, `pip install -r backend/requirements.txt -r
backend/requirements-dev.txt`, `python ml/train_classifiers.py`, `python ml/eval_sentiment.py`,
`docker compose up -d postgres redis`, `cd backend && python -m scripts.prepare_db && python -m scripts.import_dataset`, `uvicorn app.main:app --port 18000`, `cd frontend && npm i && npm run dev`.

## Signing in

`.\scripts\dev.ps1 seed` creates the organisation and prints the demo logins:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@shopzilla.example` | `Admin@12345` |
| Agent (Payments Support) | `alexander.saunders@shopzilla.example` | `Agent@12345` (every seeded agent uses it) |

Change them with `SEED_ADMIN_PASSWORD` / `SEED_AGENT_PASSWORD` in `.env` before seeding. Access tokens last 15 minutes
and are renewed automatically from an HttpOnly refresh cookie; reusing an old refresh token ends the session.

## Using it

1. **Dashboard** — volume (per day, week or month), sentiment trend, top categories and intents, emerging issues
   (for example "Payments related complaints rose 56% this week") and the open high-priority list. Switch 7 / 30 / 90 days.
2. **New complaint** — paste a complaint and press **Analyze** to preview the AI triage (category, intent,
   sentiment, priority with the rules that fired, extracted entities), then **Save**.
   Try *Fill example*: "I was charged twice for my order of ₹12,500 and have already contacted support three
   times…" → Payments related · Very Negative · ₹12,500 · repeat contact → **Critical**.
3. **Ticket details (the agent's workspace)** — complaint, customer profile and previous tickets, AI triage,
   copilot (summary, likely root cause, key issues, next steps and an editable draft reply: **accept** posts it as
   the agent's comment marked AI-assisted, **regenerate** replaces it, **discard** drops it — the AI never sends
   anything itself), comments,
   attachments and the full timeline. Correct the category if the model was wrong — priority is recomputed by the
   rules. The action bar shows only the moves the current user may make right now.
4. **Lifecycle** — 8 states: `NEW → TRIAGED → ASSIGNED → IN_PROGRESS ⇄ WAITING_CUSTOMER`, `ESCALATED`, `RESOLVED →
   CLOSED`, reopen from RESOLVED/CLOSED. The allowed moves live in one place
   ([backend/app/domain/lifecycle.py](backend/app/domain/lifecycle.py)); anything else returns HTTP 409. Every change
   is written to `ticket_events` (the timeline) and sensitive ones (reassign, escalate, close someone else's ticket,
   reopen) to `audit_logs`, in the same transaction.
5. **Ticket queue** — saved views (all open, unassigned, assigned to me, escalated, needs review, resolved & closed)
   plus search and filters over 85k+ tickets. Admins see everything; agents see their own, their team's and the
   tickets they created (other tickets return 404).
6. **Routing** — every new ticket is routed by rules (never the LLM): category → owning team → least-busy active
   agent (ties round-robin), or the team queue when nobody is free. Low-confidence categories wait in the Admin
   **Review queue**; confirming or correcting the category routes them. See [docs/ROUTING_RULES.md](docs/ROUTING_RULES.md).
7. **Similar tickets & knowledge base** — the ticket page lists similar past tickets (within what the user may
   see) and the most relevant help articles; the **Knowledge base** page searches by meaning and keywords. Admins
   create and edit articles (re-indexed on save); agents read them. The copilot is grounded in the same results and
   shows which ones it relied on ("Grounded in").
8. **Event pipeline** — creating a ticket is instant (NEW); the AI worker triages and routes it, the LLM worker
   drafts the copilot answer, and the page refreshes itself while they work. **Admin → Event pipeline** shows the
   outbox lag, what each worker processed and the dead-letter queue (replay / discard). See [docs/EVENTS.md](docs/EVENTS.md).
9. **SLA** — every triaged ticket gets a deadline from its SLA policy (Critical 2 h … Low 3 days; Admins edit them
   under **SLA policies**). The badge counts down live (green → amber at 80 % → red when breached, grey while waiting on
   the customer); a breach escalates the ticket automatically. Queue views *SLA at risk* / *SLA breached*; the
   dashboard shows the breach rate. Set `SLA_SPEEDUP=120` to watch a 2-hour SLA lapse in a minute. See [docs/SLA.md](docs/SLA.md).
10. **Notifications** — assignments, escalations and SLA warnings / breaches arrive live (bell with an unread count,
    toasts, the Notifications page) and, for escalations and SLA alerts, by e-mail when SMTP is set
    (`.\scripts\dev.ps1 up` starts Mailpit: inbox at http://localhost:18025). See [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md).
11. **My work** — the agent's start page: open tickets by state, highest priority first, and the team's unassigned
   backlog.

Permissions follow the spec: agents work on own/team tickets and may reassign within their team; reassigning to
another team and closing someone else's ticket are Admin only.

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

All routes live under `/api/v1/` (spec's API table). Everything except `/health` and `/auth/login|refresh|logout`
needs `Authorization: Bearer <access token>`; Admin-only routes return 403 for agents.

| Method | Path | Purpose |
|---|---|---|
| POST | `/ai/analyze` | Run the NLP triage pipeline on a text without saving |
| POST | `/tickets` | Create a ticket (`INC-00001` …); triage runs automatically and is recorded in `ai_analyses` |
| GET | `/tickets` | Queue (scoped to the caller) with `q`, `status` (comma list or `open`), `assignee` (`me`/`none`/id), `team_id`, `escalated`, `category`, `sentiment`, `priority`, `channel`, `source`, `needs_review`, `sort`, `page` |
| GET | `/tickets/summary` | Ticket counts per state within the caller's scope (accepts the same filters) |
| GET / PATCH | `/tickets/{id}` | Detail workspace (comments, attachments, timeline, customer, previous tickets, `allowed_actions`) · PATCH `status` (`IN_PROGRESS` / `WAITING_CUSTOMER`: start, wait, resume) or correct `category` |
| POST | `/tickets/{id}/assign`, `/escalate`, `/resolve`, `/close`, `/reopen` | Lifecycle actions (illegal moves → 409, missing permission → 403) |
| POST | `/tickets/{id}/auto-assign` | Admin: re-run the routing rules on an unassigned ticket |
| GET / POST | `/tickets/{id}/comments` · `/tickets/{id}/timeline` | Comments (first one sets `first_response_at`) · event timeline |
| POST / GET | `/tickets/{id}/attachments` · `/attachments/{aid}` | Upload (allow-listed types, content sniffed, 10 MB) · download |
| GET | `/tickets/{id}/similar` | Similar tickets (hybrid search, scoped to the caller) |
| GET | `/knowledge/search?q=` or `?ticket_id=` | Knowledge-base search (hybrid) |
| CRUD | `/knowledge` | Help articles: read for everyone, create / edit / delete for Admins (audited) |
| GET · POST · PUT | `/notifications`, `/notifications/{id}/read`, `/notifications/read-all`, `/notifications/preferences` · `/notifications/stream` (SSE) | Own notifications, unread count, e-mail preference · live stream |
| CRUD | `/sla-policies` | SLA targets per priority / category (Admin, audited) |
| GET | `/analytics/sla` | Breach rate by priority, category, team and over time; open at risk / breached (Admin) |
| GET · POST | `/admin/events` · `/admin/dlq`, `/admin/dlq/{id}/replay`, `/admin/dlq/{id}/discard` | Event pipeline status · dead-letter queue (Admin) |
| GET | `/teams/{id}/members` | Active members with their open-ticket load (agents: own team) |
| POST | `/ai/draft-response` | Copilot for `{ticket_id}`: summary, root cause, key issues, next steps, draft reply (re-running supersedes the pending draft) |
| POST | `/ai/drafts/{id}/accept` · `/ai/drafts/{id}/discard` | Agent review of a draft: accept `{response}` (as is or edited → AI-assisted comment) or discard `{reason?}` |
| GET | `/analytics/overview`, `/trends?granularity=day\|week\|month`, `/categories`, `/emerging` | Dashboard analytics (Redis-cached) |
| GET | `/health` | Model versions in use (public) |
| POST / GET | `/auth/login`, `/auth/refresh`, `/auth/logout` · `/auth/me` | Sign in (refresh token in an HttpOnly cookie), rotate, sign out · current user |
| CRUD | `/users`, `/teams`, `/departments`, `/categories` | Admin management (categories and teams are readable by agents) |
| GET | `/admin/audit-logs` | Sensitive actions (Admin) |

Interactive docs: http://localhost:18000/docs

## Project layout

```
backend/app/        FastAPI app — api/v1/ (routes), domain/ (ticket state machine), services/ (business rules),
                    events/ (outbox, Kafka relay, consumer framework), workers/ (AI, LLM, SLA, notification),
                    repositories/ (SQL), models/, schemas/, auth/, core/, ai/ (triage, classifier, sentiment,
                    entities, priority, pii, llm, embeddings)
backend/scripts/    prepare_db.py (create + migrate), seed.py (org + users + KB), seed_knowledge.py, import_dataset.py,
                    embed_tickets.py (embedding backfill)
backend/migrations/ Alembic migrations
ml/                 profile_dataset.py, train_classifiers.py, eval_sentiment.py, eval_retrieval.py +
                    retrieval_examples.py (fixed examples), reports/, MODEL_CARD.md
frontend/src/       pages/ (Dashboard, MyWork, Tickets, ReviewQueue, NewTicket, TicketDetail, Knowledge, Login, admin/), components/ (ticket/:
                    ActionBar, Conversation, Timeline, CopilotPanel, Retrieval), api/, auth/
tests/backend/      pytest (AI components, API, auth/permissions, lifecycle, routing, copilot, retrieval, dashboard)
tests/e2e/          Playwright end-to-end test of the full complaint flow
docs/               DATA_PROFILE.md, ARCHITECTURE.md, PRIORITY_RULES.md, ROUTING_RULES.md, EVENTS.md, SLA.md,
                    NOTIFICATIONS.md
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
