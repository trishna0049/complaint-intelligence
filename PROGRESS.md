# Build progress

**Goal:** the full spec in [docs/complaint_intelligence_idea.pdf](docs/complaint_intelligence_idea.pdf), with nothing
cut. The earlier simplified build (SQLite, no auth/tickets/events) is the starting point. Gaps are tracked in
[docs/GAP_REPORT.md](docs/GAP_REPORT.md). Each step is finished (code + migrations + UI + tests + checked by hand)
and committed locally before the next one starts.

| # | Step | Status |
|---|---|---|
| 1 | Infrastructure — Compose (Postgres 16 + pgvector, Redis), async SQLAlchemy 2, Alembic, re-import | ✅ |
| 2 | API alignment — `/api/v1`, tickets, `INC-` numbers, `/analytics/*` | ⏳ next |
| 3 | Auth and roles — JWT + rotating refresh tokens, argon2, ADMIN/AGENT guards, admin screens | ⏳ |
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

- Step 1 done. Infrastructure: `docker compose` project **complaint-intel** (`.\scripts\dev.ps1 up`) —
  Postgres on `localhost:15432` (databases `complaints`, `complaints_test`, `complaints_e2e`), Redis on
  `localhost:16379` (tests use Redis DB 15).
- Schema is managed by Alembic only (`backend/migrations`, `.\scripts\dev.ps1 migrate`); the API never creates tables.
- Backend layering: `api → services → repositories → models` (`app/core` holds config, db, redis).
- The old SQLite file `var/complaints.db` is no longer used (it can be deleted).
- Next: step 2 (API alignment).

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
