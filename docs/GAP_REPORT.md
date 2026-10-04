# Gap report — spec vs. implementation

Spec: [complaint_intelligence_idea.pdf](complaint_intelligence_idea.pdf) (14 pages, "Complaint Intelligence Platform —
Project Idea & Model"). This file tracks how far the repository is from that spec and is updated after every build step.

## Baseline (before the full-scope build, commit `3343734`)

The repository was a deliberately simplified version of the spec (see PROGRESS.md history): one FastAPI process on
SQLite, a React dashboard, the NLP triage pipeline and LLM insights. Status against the spec's 10-step build plan:

| # | Step | Status | Notes |
|---|---|---|---|
| 1 | Setup | ✅ Done | Repo structure, .gitignore, env template, dataset profile |
| 2 | Foundation | 🟡 Partial | FastAPI + React shell done. SQLite, not Postgres + pgvector. No Docker Compose, no login or roles. |
| 3 | Ticket engine | 🟡 Partial | CSV import, list/detail/create screens, filters. 3 states (Open, In Progress, Resolved) instead of 8. No assign, escalate, reopen, comments, attachments, timeline or audit log. |
| 4 | AI triage | ✅ Mostly | Classifiers with baseline comparison, HF sentiment validated against CSAT, regex entities, raise-only priority rules, confusion matrix, model card. Missing: spaCy entities, DistilBERT comparison. |
| 5 | Events | ❌ Not done | Kafka, outbox, workers, retries, dead-letter queue |
| 6 | Copilot | ✅ Mostly | OpenAI structured outputs, mock, PII masking, summary, key issues, actions, draft reply, token cost. Missing: root cause, RAG grounding, accept/regenerate/discard. |
| 7 | Retrieval | ❌ Not done | Embeddings, similar tickets, knowledge base, RAG |
| 8 | SLA and notifications | ❌ Not done | Deadlines, countdowns, 80% warning / 100% escalation, alerts, email |
| 9 | Analytics | 🟡 Partial | KPIs, daily trend, CSAT, categories/intents/channels, emerging issues, insights. Missing: SLA breach rate, resolution and first-response times, repeat-complaint rate, city/product, workload, week/month views, "My stats". |
| 10 | Production | 🟡 Partial | pytest, Vitest, Playwright, lint, CI, docs. Missing: Docker images, Trivy, GHCR, Prometheus/Grafana, rate limiting, security headers, deployment guide, Makefile. |

Other differences: routes under `/api/` not `/api/v1/`; `complaints` instead of `tickets` (`CMP-` vs `INC-`);
`/dashboard` instead of `/analytics/*`; a stray, empty `docker/postgres/init.sh` directory.

## Full-scope build — progress

| Step | Scope | Status |
|---|---|---|
| 1 | Infrastructure: Compose (Postgres 16 + pgvector, Redis), async SQLAlchemy, Alembic, re-import | ✅ Done |
| 2 | API alignment: `/api/v1`, tickets, `INC-`, `/analytics/*` | ✅ Done (`/analytics/sla` and `/workload` arrive with steps 9 and 11, once SLA and assignment data exist) |
| 3 | Auth and roles | ⏳ Not started |
| 4 | Full ticket lifecycle | ⏳ Not started |
| 5 | Routing | ⏳ Not started |
| 6 | Copilot completion | ⏳ Not started |
| 7 | Retrieval (embeddings, KB, RAG) | ⏳ Not started |
| 8 | Events (Kafka, outbox, workers, DLQ) | ⏳ Not started |
| 9 | SLA engine | ⏳ Not started |
| 10 | Notifications | ⏳ Not started |
| 11 | Analytics completion | ⏳ Not started |
| 12 | AI triage gaps (spaCy, DistilBERT) | ⏳ Not started |
| 13 | Production | ⏳ Not started |
| 14 | Tests | ⏳ Not started |

## Known deviations / impossible on this machine

_None yet._
