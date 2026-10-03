# Build progress

Tracks the spec's 10-step build plan. Each phase is finished (code + tests + verified by hand) before the next starts.

| # | Phase | Status |
|---|---|---|
| 1 | Setup — structure, .gitignore, .env.example, dataset profile | ✅ done |
| 2 | Foundation — Docker, schema, FastAPI, auth, React shell, seed | ⏳ |
| 3 | Ticket engine — workflow, permissions, CSV import, ticket screens | ⏳ |
| 4 | AI triage — classifiers, sentiment, entities, priority, evaluation | ⏳ |
| 5 | Events — Kafka, outbox, workers, routing, retries, DLQ | ⏳ |
| 6 | Copilot — LLM summaries, actions, draft replies, PII masking | ⏳ |
| 7 | Retrieval — embeddings, similar tickets, KB, RAG | ⏳ |
| 8 | SLA and notifications — deadlines, countdowns, escalation, alerts | ⏳ |
| 9 | Analytics — dashboard, KPIs, trends, insights, My stats | ⏳ |
| 10 | Production — security, monitoring, tests, CI/CD, docs | ⏳ |

## Notes
- Phase 1: `ml/profile_dataset.py` → `docs/DATA_PROFILE.md`. Key finding: `Customer Remarks` (33.5% filled, median 3 words)
  are mostly survey feedback ("Good", "Thank you"), so text-only category accuracy is inherently limited.
