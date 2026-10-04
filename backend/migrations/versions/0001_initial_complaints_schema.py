"""initial complaints schema

Revision ID: 0001
Revises:
Create Date: 2026-10-05 04:07:50.166289
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE SEQUENCE IF NOT EXISTS complaint_reference_seq START 1")
    op.create_table(
        "complaints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "reference",
            sa.String(length=16),
            server_default=sa.text("'CMP-' || lpad(nextval('complaint_reference_seq')::text, 6, '0')"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_is_template", sa.Boolean(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=True),
        sa.Column("order_id", sa.String(length=64), nullable=True),
        sa.Column("product", sa.String(length=120), nullable=True),
        sa.Column("amount_inr", sa.Float(), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("csat_score", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("category_confidence", sa.Float(), nullable=True),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("intent_confidence", sa.Float(), nullable=True),
        sa.Column("sentiment", sa.String(length=16), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("priority_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("labels_from", sa.String(length=16), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_complaints")),
        sa.UniqueConstraint("external_id", name=op.f("uq_complaints_external_id")),
        sa.UniqueConstraint("reference", name=op.f("uq_complaints_reference")),
    )
    op.create_index(op.f("ix_complaints_category"), "complaints", ["category"], unique=False)
    op.create_index(op.f("ix_complaints_created_at"), "complaints", ["created_at"], unique=False)
    op.create_index("ix_complaints_created_category", "complaints", ["created_at", "category"], unique=False)
    op.create_index(op.f("ix_complaints_priority"), "complaints", ["priority"], unique=False)
    op.create_index(op.f("ix_complaints_sentiment"), "complaints", ["sentiment"], unique=False)
    op.create_index(op.f("ix_complaints_status"), "complaints", ["status"], unique=False)
    op.create_table(
        "ai_insights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("complaint_id", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("key_issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recommended_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("customer_reply", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column("usage", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["complaint_id"], ["complaints.id"], name=op.f("fk_ai_insights_complaint_id_complaints"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_insights")),
    )
    op.create_index(op.f("ix_ai_insights_complaint_id"), "ai_insights", ["complaint_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_insights_complaint_id"), table_name="ai_insights")
    op.drop_table("ai_insights")
    op.drop_index(op.f("ix_complaints_status"), table_name="complaints")
    op.drop_index(op.f("ix_complaints_sentiment"), table_name="complaints")
    op.drop_index(op.f("ix_complaints_priority"), table_name="complaints")
    op.drop_index("ix_complaints_created_category", table_name="complaints")
    op.drop_index(op.f("ix_complaints_created_at"), table_name="complaints")
    op.drop_index(op.f("ix_complaints_category"), table_name="complaints")
    op.drop_table("complaints")
    op.execute("DROP SEQUENCE IF EXISTS complaint_reference_seq")
