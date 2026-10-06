# Architecture

A FastAPI API and four Kafka workers on async SQLAlchemy 2, PostgreSQL 16 (+ pgvector), Redis and Apache Kafka (KRaft)
in Docker Compose, one React app. The API writes tickets and their events in one transaction (outbox); a relay
publishes them to Kafka and the AI, LLM, SLA and notification workers process them ([EVENTS.md](EVENTS.md)). This
document is rewritten in full as the platform grows.

```mermaid
flowchart LR
    UI["React app<br/>(Vite, Tailwind, React Query, Recharts)"] -- "/api/v1 (JSON, Bearer JWT)" --> API["FastAPI"]
    API --> AUTH["Auth<br/>JWT + rotating refresh cookie, argon2"]
    API --> T["Triage pipeline"]
    T --> C["scikit-learn<br/>category + intent"]
    T --> S["Hugging Face<br/>5-level sentiment"]
    T --> E["Regex entities<br/>₹ amounts, order IDs, dates"]
    T --> P["Priority rules<br/>(raise-only)"]
    API --> LC["Lifecycle state machine<br/>(8 states, 409 on illegal moves)"]
    API --> RT["Routing rules<br/>team → least-busy agent"]
    API --> RET["Hybrid retrieval<br/>MiniLM + pgvector HNSW · full text · RRF"]
    RET --> DB
    API --> L["Copilot (LLM)<br/>OpenAI structured output · Mock<br/>grounded in KB + similar tickets"]
    L -. "PII masked first" .-> OAI(("OpenAI API"))
    API --> DB[("PostgreSQL 16<br/>tickets, ticket_events, users, teams, …")]
    API --> R[("Redis<br/>analytics cache")]
    DB -- "outbox" --> RELAY["Outbox relay"] --> K[["Kafka (KRaft)<br/>one topic per event type"]]
    K --> W1["AI worker<br/>triage · routing · embeddings"]
    K --> W2["LLM worker<br/>copilot draft"]
    K --> W3["SLA worker"]
    K --> W4["Notification worker"]
    W1 & W2 & W3 & W4 --> DB
```

## Request flows

**New ticket** — `POST /api/v1/tickets` returns at once; the AI work happens in the workers

```mermaid
sequenceDiagram
    participant UI
    participant API as FastAPI
    participant DB as PostgreSQL
    participant K as Kafka
    participant AIW as AI worker
    participant LLMW as LLM worker
    UI->>API: complaint text + optional customer/order/amount/product
    API->>DB: ticket (NEW) + timeline "created" + outbox ticket.created — one transaction
    API-->>UI: 201 ticket (NEW); the page polls while triage is pending
    DB-->>K: relay publishes ticket.created (key = ticket id)
    K->>AIW: ticket.created
    AIW->>DB: triage (entities, category, intent, sentiment, priority rules), routing rules (team → least-busy agent),<br/>MiniLM embedding, outbox ai.analysis.completed + ticket.assigned, processed_events — one transaction
    K->>LLMW: ai.analysis.completed
    LLMW->>DB: copilot draft grounded in KB + similar tickets (pending until an agent accepts it)
```

**Lifecycle actions** — `POST /tickets/{id}/assign|escalate|resolve|close|reopen`, `PATCH /tickets/{id}`: the ticket
row is locked, permissions are checked (Admin vs own/team), the move is checked against
`app/domain/lifecycle.py`, and the change, its `ticket_events` row and (for sensitive actions) its `audit_logs` row
are committed together.

**Retrieval** — `GET /tickets/{id}/similar`, `GET /knowledge/search`: the query is embedded with MiniLM (384 dims);
nearest neighbours come from the pgvector HNSW index (iterative scan, so visibility filters still return enough rows)
and keyword matches from PostgreSQL full text; the two rankings are fused with weighted Reciprocal Rank Fusion
(keywords 0.3, vectors 1.0), weak vector matches are dropped. See ml/reports/retrieval_report.md.

**Copilot** — `POST /api/v1/ai/draft-response`: the most relevant help articles and similar past tickets (within the
caller's visibility) are added as references [A1].., [T1]..; the complaint, conversation and references are
PII-masked (the ticket's own customer becomes [CUSTOMER] and is restored locally in the answer); the LLM returns a
schema (summary, root cause, key issues, next steps, draft reply, references used) that is stored as an
`ai_analyses` row with provider, model, prompt version, token cost and grounding. The draft is posted only when an
agent accepts it (`/ai/drafts/{id}/accept`).

**Analytics** — `GET /api/v1/analytics/overview|trends|categories|emerging` (Admin): SQL `GROUP BY` / `CASE`
aggregates, cached in Redis and invalidated on every write.

## Code layout

| Path | What lives there |
|---|---|
| `backend/app/api/v1/` | HTTP routes (thin — parse, call a service, serialise) |
| `backend/app/domain/` | Pure rules: `lifecycle.py` (states and moves), `routing.py` (team + agent choice) |
| `backend/app/services/` | Business logic: tickets, routing, admin, auth, analytics, attachment storage |
| `backend/app/repositories/` | SQL only (no rules) |
| `backend/app/models/`, `schemas/` | SQLAlchemy tables and Pydantic request/response shapes |
| `backend/app/auth/` | JWT, password hashing, `CurrentUser` / `AdminUser` dependencies |
| `backend/app/events/` | Event catalogue + envelope, outbox writes, inline bus, Kafka relay and consumer loop, consumer framework (idempotency, retries, DLQ) |
| `backend/app/workers/` | The four workers (AI, LLM, SLA, notification) and `run.py` (`python -m app.workers.run ...`) |
| `backend/app/ai/` | `triage.py` orchestrates `classifier.py`, `sentiment.py`, `entities.py`, `priority.py`; `llm.py` + `pii.py` for the copilot; `embeddings.py` (MiniLM, hashing fallback) |
| `backend/migrations/` | Alembic migrations (the only way the schema changes) |
| `backend/scripts/` | `prepare_db.py`, `seed.py` (org + users), `import_dataset.py` (history, linked to agents and teams) |
| `ml/` | Dataset profile, classifier training, sentiment validation, reports, model card |
| `frontend/src/pages/` | Dashboard, My work, Ticket queue, Review queue, Create ticket, Ticket details, Login, admin screens |

## Design decisions

- **AI for language, rules for decisions.** Category, intent and sentiment come from models; priority and routing
  are documented rule sets ([PRIORITY_RULES.md](PRIORITY_RULES.md), [ROUTING_RULES.md](ROUTING_RULES.md)) because
  the decisions must be explainable — every ticket stores which rules fired.
- **Human in the loop.** Low-confidence categories are not routed; they wait in the review queue until a person
  confirms or corrects them. The LLM's reply is a draft — nothing is sent automatically.
- **One place for the lifecycle.** Allowed moves are data in `app/domain/lifecycle.py`; the API, the UI's buttons
  (`allowed_actions`) and the tests all derive from it.
- **Works offline.** `LLM_PROVIDER=mock` produces realistic copilot output without a key; `LLM_PROVIDER=openai` and
  `OPENAI_API_KEY` switch to the real API with structured outputs.
- **PostgreSQL + Alembic.** Async SQLAlchemy 2 with asyncpg; CPU-bound model inference runs in worker threads off
  the event loop.
