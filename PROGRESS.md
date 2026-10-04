# Build progress

**Goal:** the full spec in [docs/complaint_intelligence_idea.pdf](docs/complaint_intelligence_idea.pdf), with nothing
cut. The earlier simplified build (SQLite, no auth/tickets/events) is the starting point. Gaps are tracked in
[docs/GAP_REPORT.md](docs/GAP_REPORT.md). Each step is finished (code + migrations + UI + tests + checked by hand)
and committed locally before the next one starts.

| # | Step | Status |
|---|---|---|
| 1 | Infrastructure — Compose (Postgres 16 + pgvector, Redis), async SQLAlchemy 2, Alembic, re-import | ✅ |
| 2 | API alignment — `/api/v1`, tickets, `INC-` numbers, `/analytics/*` | ✅ |
| 3 | Auth and roles — JWT + rotating refresh tokens, argon2, ADMIN/AGENT guards, admin screens | ⏳ next |
| 4 | Full ticket lifecycle — 8 states, assign/escalate/resolve/close/reopen, comments, attachments, timeline, audit | ⏳ |
| 5 | Routing — category → team → least-busy agent; low-confidence review queue | ⏳ |
| 6 | Copilot completion — root cause, prompt_version, accept / regenerate / discard | ⏳ |
| 7 | Retrieval — MiniLM embeddings, HNSW, hybrid search, similar tickets, knowledge base, RAG | ⏳ |
| 8 | Events — Kafka (KRaft) + UI, outbox relay, 4 workers, idempotency, retries, DLQ + replay | ⏳ |
| 9 | SLA engine — policies, pause rule, warning/breach once, auto-escalation, live badge, demo speed-up | ⏳ |
| 10 | Notifications — table, SSE via Redis pub/sub, bell, page, toasts, optional SMTP | ⏳ |
| 11 | Analytics completion — SLA/timing/repeat/city/product/workload, day/week/month, My stats | ⏳ |
| 12 | AI triage gaps — spaCy entities, DistilBERT comparison | ⏳ |
| 13 | Production — rate limits, headers, metrics, Grafana, Dockerfiles, Makefile, CI (Trivy, GHCR), docs | ⏳ |
| 14 | Tests — unit, permissions, Kafka integration, full Playwright flow | ⏳ |

## Where things stand (resume here)

- Steps 1–2 done. Infrastructure: `docker compose` project **complaint-intel** (`.\scripts\dev.ps1 up`) —
  Postgres on `localhost:15432` (databases `complaints`, `complaints_test`, `complaints_e2e`), Redis on
  `localhost:16379` (tests use Redis DB 15).
- Schema is managed by Alembic only (`backend/migrations`, `.\scripts\dev.ps1 migrate`); the API never creates tables.
- Backend layering: `api → services → repositories → models` (`app/core` holds config, db, redis).
- The old SQLite file `var/complaints.db` is no longer used (it can be deleted).
- API: everything under `/api/v1` (`tickets`, `ai/analyze`, `ai/draft-response`, `analytics/*`, `health`,
  `categories`). Tables `tickets` (numbers `INC-00001`, from `next_ticket_number()`) and `ai_analyses`
  (`kind` = triage | copilot). Frontend routes `/tickets`, `/tickets/new`, `/tickets/:id` (old `/complaints/*`
  links redirect).
- Next: step 3 (auth and roles).

## Step log

### Step 1 — Infrastructure ✅
- `docker-compose.yml` (project `complaint-intel`): `pgvector/pgvector:pg16` + `redis:7.4-alpine`, ports from `.env`.
  The old stopped `complaint-intel` project (stale schema, broken `init.sh` bind mount) was removed with its volumes;
  the stray `docker/postgres/init.sh` directory is gone. `docker/postgres/initdb/` creates the test database.
- Async SQLAlchemy 2 + asyncpg (`app/core/db.py`), Alembic (`0001` initial schema incl. `vector` and `pg_trgm`
  extensions and the reference sequence), `scripts/prepare_db.py` (create DB + migrate, `--reset`).
- Importer is async, batched (5,000 rows/transaction), idempotent (pre-filter + `ON CONFLICT DO NOTHING`):
  85,907 rows in ~73 s; a re-run inserts 0.
- Dashboard cached in Redis (generation-counter invalidation on writes); uncached dashboard 0.36–0.47 s on 85,907
  rows (was ~3.4 s on SQLite).
- Tests run on the Postgres test DB (migrated by Alembic each run, truncated per test): 38 passed. Playwright e2e
  passes against its own `complaints_e2e` database. CI gets Postgres + Redis service containers.

### Step 2 — API alignment ✅
- Migration `0002`: `complaints → tickets` (`reference → ticket_number`, `CMP-000123 → INC-00123`, sequence +
  `next_ticket_number()` that pads to five digits and grows beyond), `text → description`, `description_source`
  (customer / dataset_remark / template), `updated_at`, `first_response_at` (dataset `issue_responded`);
  `ai_insights → ai_analyses` with the spec's fields (triage snapshot, confidence, model_version, recommendations,
  draft_response). Upgrade/downgrade round-trip tested; `alembic check` reports no drift.
- Routers split under `app/api/v1/` (meta, tickets, ai, analytics); schemas package; analytics split into
  `/analytics/overview`, `/trends` (day/week/month via `date_trunc`), `/categories`, `/emerging`.
- Every triage run is recorded as an `ai_analyses` row (kind=triage); the copilot stores kind=copilot rows.
- Bug found by hand: dev and e2e APIs shared Redis DB 0, so the dev dashboard showed the e2e database's cached
  numbers. Cache keys are now namespaced by database name (regression test added) and e2e uses Redis DB 14.
- Tests: 43 backend, 11 frontend, Playwright e2e — all pass. Checked by hand on the full dataset (dashboard, list,
  detail screenshots).
