# Build progress

**Goal:** the full spec in [docs/complaint_intelligence_idea.pdf](docs/complaint_intelligence_idea.pdf), with nothing
cut. The earlier simplified build (SQLite, no auth/tickets/events) is the starting point. Gaps are tracked in
[docs/GAP_REPORT.md](docs/GAP_REPORT.md). Each step is finished (code + migrations + UI + tests + checked by hand)
and committed locally before the next one starts.

| # | Step | Status |
|---|---|---|
| 1 | Infrastructure — Compose (Postgres 16 + pgvector, Redis), async SQLAlchemy 2, Alembic, re-import | ✅ |
| 2 | API alignment — `/api/v1`, tickets, `INC-` numbers, `/analytics/*` | ✅ |
| 3 | Auth and roles — JWT + rotating refresh tokens, argon2, ADMIN/AGENT guards, admin screens | ✅ |
| 4 | Full ticket lifecycle — 8 states, assign/escalate/resolve/close/reopen, comments, attachments, timeline, audit | ✅ |
| 5 | Routing — category → team → least-busy agent; low-confidence review queue | ✅ |
| 6 | Copilot completion — root cause, prompt_version, accept / regenerate / discard | ✅ |
| 7 | Retrieval — MiniLM embeddings, HNSW, hybrid search, similar tickets, knowledge base, RAG | ⏳ next |
| 8 | Events — Kafka (KRaft) + UI, outbox relay, 4 workers, idempotency, retries, DLQ + replay | ⏳ |
| 9 | SLA engine — policies, pause rule, warning/breach once, auto-escalation, live badge, demo speed-up | ⏳ |
| 10 | Notifications — table, SSE via Redis pub/sub, bell, page, toasts, optional SMTP | ⏳ |
| 11 | Analytics completion — SLA/timing/repeat/city/product/workload, day/week/month, My stats | ⏳ |
| 12 | AI triage gaps — spaCy entities, DistilBERT comparison | ⏳ |
| 13 | Production — rate limits, headers, metrics, Grafana, Dockerfiles, Makefile, CI (Trivy, GHCR), docs | ⏳ |
| 14 | Tests — unit, permissions, Kafka integration, full Playwright flow | ⏳ |

## Where things stand (resume here)

- Steps 1–3 done. Infrastructure: `docker compose` project **complaint-intel** (`.\scripts\dev.ps1 up`) —
  Postgres on `localhost:15432` (databases `complaints`, `complaints_test`, `complaints_e2e`), Redis on
  `localhost:16379` (tests use Redis DB 15).
- Schema is managed by Alembic only (`backend/migrations`, `.\scripts\dev.ps1 migrate`); the API never creates tables.
- Backend layering: `api → services → repositories → models` (`app/core` holds config, db, redis).
- The old SQLite file `var/complaints.db` is no longer used (it can be deleted).
- API: everything under `/api/v1` (`tickets`, `ai/analyze`, `ai/draft-response`, `analytics/*`, `health`,
  `categories`). Tables `tickets` (numbers `INC-00001`, from `next_ticket_number()`) and `ai_analyses`
  (`kind` = triage | copilot). Frontend routes `/tickets`, `/tickets/new`, `/tickets/:id` (old `/complaints/*`
  links redirect).
- Auth: `POST /auth/login` → access token (15 min JWT, kept in memory by the SPA) + refresh token in an HttpOnly
  cookie (`ci_refresh`, path `/api/v1/auth`, rotated on every refresh, reuse revokes the family). Seeded by
  `.\scripts\dev.ps1 seed`: admin `admin@shopzilla.example` / `Admin@12345`, every dataset agent with
  `Agent@12345` (Payments Support demo agent: `alexander.saunders@shopzilla.example`).
- Lifecycle: 8 states, moves defined only in `backend/app/domain/lifecycle.py` (illegal → 409). Every change writes a
  `ticket_events` row (timeline) — and `audit_logs` for reassign / escalate / close-other / reopen — in the same
  transaction. Agents see own + team + created tickets (others → 404). Imported history is `CLOSED`, linked to its
  dataset agent and the category's team.
- Routing (rules, [docs/ROUTING_RULES.md](docs/ROUTING_RULES.md)): on create, after triage, in the same transaction —
  category → owning team → least-busy active agent (per-team advisory lock); low confidence → Admin **Review queue**
  (`/review`); confirming/correcting the category routes untouched tickets; Admin "Auto-assign". Triage + routing
  still run inside the request — step 8 moves them to the Kafka AI worker.
- Copilot (`app/services/copilot.py`, prompt `copilot-v2`): summary, root cause, key issues, next steps, draft reply;
  each run is `pending` until an agent accepts (posted as their `ai_assisted` comment, edited or not) or discards it;
  re-running supersedes the pending draft. RAG grounding (similar tickets + KB) is added to its context in step 7.
- Next: step 7 (retrieval: MiniLM embeddings, pgvector HNSW, hybrid search, similar tickets, knowledge base, RAG).

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

### Step 3 — Auth and roles ✅
- Migration `0003`: `departments`, `teams`, `users` (role ADMIN/AGENT, team, active, dataset supervisor),
  `categories` (with the owning team, used by routing in step 5), `refresh_tokens` (hash only, family, rotation
  chain, revoke reason) and `audit_logs`.
- argon2id passwords (constant-time path for unknown e-mails); JWT access tokens (role re-read from the DB on every
  request, so demotions and deactivations apply immediately); refresh rotation with reuse detection (reuse →
  whole family revoked + audit) and a 10 s leeway that returns a retryable 409 for two tabs refreshing at once.
- Endpoints: `/auth/login|refresh|logout|me`; Admin CRUD `/users` (deactivate, never delete), `/teams`,
  `/departments`, `/categories` (read for everyone); `/admin/audit-logs`. Analytics is Admin only (agents get
  "My stats" in step 11). Built-in dataset categories can't be renamed or deleted (classifier + priority rules
  depend on the names); their owning team can change.
- `PUBLIC_ROUTES` in `app/api/v1/__init__.py`; `test_every_non_public_route_depends_on_current_user` (structural)
  and `..._returns_401_without_a_token` (behavioural) fail if a route lacks auth; every `require_admin` route is
  checked to return 403 for agents.
- Seed (`scripts/seed.py`, idempotent): 3 departments, 12 category teams (e.g. Payments Support), 12 categories,
  1 admin, 1,371 dataset agents (supervisor groups allocated to teams in proportion to category volume; ~60 s
  for argon2). `--agents-per-team N` keeps e2e setup fast.
- Frontend: login page, `AuthProvider` (session restore from the cookie, proactive refresh 60 s before expiry,
  single-flight refresh + retry on 401, 409 retry), `RequireAuth` / `RequireRole`, sidebar layout with
  role-aware sections and user menu, admin Users / Teams / Categories screens with loading, empty and error states.
- Checked by hand: screenshots of login, admin users/teams/categories, agent view and the agent's no-access page;
  curl run of login → refresh → old cookie within 10 s (409) → after 10 s (401, family revoked).
- Tests: 72 backend (24 new auth/permission tests), 20 frontend (9 new), Playwright e2e signs in first.

### Step 4 — Full ticket lifecycle ✅
- `app/domain/lifecycle.py`: the 8 states (NEW, TRIAGED, ASSIGNED, IN_PROGRESS, WAITING_CUSTOMER, ESCALATED, RESOLVED,
  CLOSED) and 9 actions with their source/target states — the only place moves are defined. Reopen goes back to the
  owner (IN_PROGRESS) or the pool (TRIAGED). `SLA_PAUSED_STATUSES = {WAITING_CUSTOMER}` is ready for the SLA engine.
- Migration `0004`: `customers` (`CUS-00001` codes, segment, region), `ticket_comments` (`ai_assisted`),
  `ticket_events` (timeline, JSONB metadata), `ticket_attachments`; tickets get `customer_id`, `created_by_id`,
  `assignee_id`, `team_id`, `resolution`, `reopen_count`, `escalated_at`, `closed_at`. Data: imported rows → CLOSED,
  app rows mapped to the new states, team filled from the category's owning team. Round-trip (0004 → 0003 → 0004)
  and `alembic check` clean.
- Endpoints: `POST /tickets/{id}/assign|escalate|resolve|close|reopen`, `PATCH /tickets/{id}` (start / wait on
  customer / resume, category correction), `GET|POST /tickets/{id}/comments`, `GET /tickets/{id}/timeline`,
  `POST|GET /tickets/{id}/attachments[/{aid}]`, `GET /tickets/summary`, `GET /teams/{id}/members` (open load).
  Detail returns `allowed_actions` (state machine ∩ permissions) so the UI only shows legal buttons.
- Permissions (spec table): agents see own/team/created tickets (others 404, no number leaks via search), work on
  own/team tickets, reassign within their team only, may not close someone else's ticket (Admin only, audited).
- Attachments: allow-listed types, magic-byte check (an .exe renamed to .pdf is rejected), size limit while
  streaming, random storage key (user filename only displayed), `Content-Disposition: attachment` + `nosniff`.
- Importer `link_history`: 85,907 historical tickets linked to their dataset agent (Agent_name) and team (idempotent).
  Historical tickets show a timeline from their real timestamps (received → first response → closed + CSAT).
- Frontend: action bar + assign (team picker for admins, agents sorted by open load, "least busy"), escalate/reopen
  reason and resolve dialogs, conversation (comments + attachments), timeline, customer card with previous tickets,
  queue views (open, unassigned, mine, escalated, needs review, done, all) with assignee/team columns, **My work**
  page (agents now land there), 8-state badges.
- Checked by hand on the full dataset (agent: My work, create → assign to self → start → comment; admin: queue and a
  historical ticket's timeline). Fixed while checking: "customer since 0 seconds" → a date; self-assignment reads
  "took the ticket"; previous tickets were serialised from raw ORM objects (Pydantic warning).
- Tests: 157 backend (85 new: all 72 state/action pairs, full API lifecycle, 409s, same-transaction rollback of
  event + audit, visibility and assignment/close permissions, comments, attachments, customers, filters), 28
  frontend (8 new lifecycle UI tests), Playwright e2e now walks assign → start → comment + attachment → resolve →
  close and checks the timeline.

### Step 5 — Routing ✅
- `app/domain/routing.py` (pure): REVIEW (confidence < 0.45) → NO_TEAM → NO_AGENTS → AT_CAPACITY
  (`ROUTING_MAX_OPEN_PER_AGENT`, 25) → LEAST_BUSY (fewest open tickets; ties: never assigned, then least recently
  assigned, then lowest id → round-robin on equal load). Documented in docs/ROUTING_RULES.md.
- `app/services/routing.py` applies a decision in the caller's transaction: assignee/team, lifecycle move,
  `routed` timeline event (rule, reason, team, agent, load, candidates), `ticket.reroute` audit when a ticket is
  taken from someone. A per-team `pg_advisory_xact_lock` stops two simultaneous tickets picking the same agent
  (the concurrency test fails without it — checked by disabling the lock).
- Migration `0005`: `users.last_assigned_at`, `ai_analyses.alternatives` (top categories), partial index for the
  review queue. Round-trip and `alembic check` clean. Lifecycle gains a system-only `release` move
  (ASSIGNED → TRIAGED) for a category fix that sends an untouched ticket to a team with no free agent.
- Runs on create, after a category is confirmed (same value on a flagged ticket) or corrected (only while nobody has
  started: TRIAGED unassigned, or ASSIGNED outside the new team — in-progress tickets keep their owner), and on
  Admin `POST /tickets/{id}/auto-assign`.
- Bug found by a test and fixed: an agent whose category fix routed the ticket to another team got a 404 for their
  own successful change. The response now carries the result with `can_view: false`, and the UI shows "INC-… moved
  to Returns & Pickups" instead of an error.
- Frontend: Admin **Review queue** page (AI suggestion + confidence, top alternatives as one-click choices, other
  category, "Just reviewed" list showing where each went), confirm/alternatives on the ticket page, routing reason in
  the Assignment card, timeline wording for routing (rules vs a person's step), Admin "Auto-assign" action.
- Checked by hand on the full dataset: a delayed-order complaint → Order Support, least busy of 259 agents; two
  ambiguous complaints (40%, 39%) → review queue with sensible alternatives; confirming one routed it to Refunds Desk
  (57 agents). Fixed while checking: the timeline credited the Admin with the rules' moves after a confirmation.
- Tests: 184 backend (27 new: every rule and tie-break, least-busy across loads, inactive/admin skipped,
  round-robin, concurrency, capacity, team queue, unrouted, review → confirm, correction moves/releases/keeps owner,
  auto-assign permissions and 409s, manual assignment counts for round-robin), 35 frontend (7 new), Playwright e2e
  checks the routing decision and a manual reassignment.

### Step 6 — Copilot completion ✅
- Prompt `copilot-v2` (structured output `ComplaintInsight`): adds `root_cause` (a hypothesis to verify) and the
  ticket's last 6 comments as context, PII-masked like the complaint (customer and commenter names, phones, e-mails).
  The prompt tells the model to treat the team's notes as established facts.
- Migration `0006`: `ai_analyses.root_cause` and the human review of each draft — `draft_status` (pending /
  accepted / discarded / superseded), `reviewed_by_id`, `reviewed_at`, `final_response`, `edited`, `comment_id`,
  `discard_reason`; existing copilot rows → newest per ticket pending, older superseded (checked on seeded rows).
- `POST /ai/draft-response` (generate / regenerate: the old pending draft becomes superseded),
  `POST /ai/drafts/{id}/accept` (the agent's final text becomes their comment marked `ai_assisted`, sets first
  response; `edited` and a similarity score are recorded) and `/discard` (optional reason). Only pending drafts can be
  reviewed (409 otherwise); drafts on tickets the user can't see → 404. Timeline events copilot_generated (with
  `regenerated`), copilot_accepted, copilot_discarded.
- The read transaction now ends before the LLM call (no connection idle in a transaction for up to 30 s). A
  schema-violating answer from a compatible endpoint is a clear `llm_invalid_output` error instead of a 500 (found
  by a test).
- Frontend: `CopilotPanel` with the likely root cause (marked as a hypothesis), editable draft ("Edited" badge,
  "Accept edited reply"), discard with optional reason, regenerate that warns before dropping unsaved edits,
  accepted/discarded states with who and when; timeline wording for every copilot event.
- Checked by hand with the real OpenAI API (gpt-4o-mini, ~600 tokens, ~$0.0002, 3.6 s): valid v2 output with root
  cause. The first answer ignored the agent's note that the gateway was already checked, so the prompt was tightened
  — the regenerated answer leads with the refund. Edited the draft in the UI and accepted it: it appeared as the
  agent's AI-assisted comment, and the timeline shows run → regenerate → posted → accepted after editing.
- Tests: 202 backend (17 new copilot tests + malformed-output error case), 42 frontend (7 new), Playwright e2e now
  checks the root cause and edits + accepts the draft before any comment exists.
