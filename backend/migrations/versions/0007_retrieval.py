"""Retrieval: ticket_embeddings and knowledge_articles (pgvector 384-dim HNSW cosine indexes), full-text columns for
the keyword half of hybrid search, and ai_analyses.grounding (RAG sources given to and cited by the copilot).

Embeddings are filled by `python -m scripts.embed_tickets` (and on ticket creation), articles by
`python -m scripts.seed_knowledge`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-06 05:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ARTICLE_TSV = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(body, '')), 'B')"
)
HNSW = {"m": 16, "ef_construction": 64}


def upgrade() -> None:
    op.create_table(
        "ticket_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_embeddings_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_embeddings")),
        sa.UniqueConstraint("ticket_id", "model_name", name="uq_ticket_embeddings_ticket_model"),
    )
    op.create_index(
        "ix_ticket_embeddings_hnsw",
        "ticket_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with=HNSW,
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "knowledge_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("usage_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), sa.Computed(ARTICLE_TSV, persisted=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_knowledge_articles_created_by_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["users.id"], name=op.f("fk_knowledge_articles_updated_by_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_articles")),
        sa.UniqueConstraint("title", name=op.f("uq_knowledge_articles_title")),
    )
    op.create_index(op.f("ix_knowledge_articles_category"), "knowledge_articles", ["category"], unique=False)
    op.create_index(
        "ix_knowledge_articles_hnsw",
        "knowledge_articles",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with=HNSW,
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_knowledge_articles_search", "knowledge_articles", ["search_vector"], postgresql_using="gin")
    op.add_column(
        "tickets",
        sa.Column(
            "description_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', coalesce(description, ''))", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_tickets_description_tsv", "tickets", ["description_tsv"], postgresql_using="gin")
    op.add_column("ai_analyses", sa.Column("grounding", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_analyses", "grounding")
    op.drop_index("ix_tickets_description_tsv", table_name="tickets", postgresql_using="gin")
    op.drop_column("tickets", "description_tsv")
    op.drop_index("ix_knowledge_articles_search", table_name="knowledge_articles", postgresql_using="gin")
    op.drop_index("ix_knowledge_articles_hnsw", table_name="knowledge_articles")
    op.drop_index(op.f("ix_knowledge_articles_category"), table_name="knowledge_articles")
    op.drop_table("knowledge_articles")
    op.drop_index("ix_ticket_embeddings_hnsw", table_name="ticket_embeddings")
    op.drop_table("ticket_embeddings")
