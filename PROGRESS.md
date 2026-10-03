# Build progress

The project was first scoped as a large event-driven platform (Kafka, workers, Postgres/pgvector, SLA engine,
JWT roles). On request it was **simplified** to the core described in the project summary:

> NLP pipeline (Hugging Face Transformers + scikit-learn) that classifies complaints by category, sentiment,
> intent and priority; OpenAI API to summarise complaints, extract key issues and recommend actions; FastAPI
> backend; React dashboards tracking trends, sentiment and high-priority issues.

| Step | Status |
|---|---|
| Dataset profile (`ml/profile_dataset.py` → `docs/DATA_PROFILE.md`) | ✅ |
| Category + intent classifiers (TF-IDF + LR baseline vs text + structured), evaluation report | ✅ |
| Hugging Face sentiment (5 levels) validated against CSAT | ✅ |
| Entities (regex), raise-only priority rules, PII masking | ✅ |
| LLM insights — OpenAI structured outputs + offline mock | ✅ |
| FastAPI backend (SQLite) + idempotent dataset importer | ✅ |
| React dashboard, complaints list, new complaint (live triage), complaint detail (AI insights) | ✅ |
| Tests (pytest + Vitest), lint, GitHub Actions CI | ✅ |
| Docs: README, architecture, priority rules, model card | ✅ |

Removed in the simplification: Kafka + outbox + workers + DLQ, Redis, Postgres/pgvector + embeddings/RAG,
JWT auth and roles, SLA engine, notifications, Prometheus/Grafana, Docker images.
