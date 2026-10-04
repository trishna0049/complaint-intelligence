"""Rename complaints -> tickets (INC- numbers) and ai_insights -> ai_analyses, aligned with the spec's data model.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEXT_TICKET_NUMBER = """
CREATE OR REPLACE FUNCTION next_ticket_number() RETURNS text LANGUAGE sql VOLATILE AS $$
    SELECT 'INC-' || CASE WHEN n < 100000 THEN lpad(n::text, 5, '0') ELSE n::text END
    FROM (SELECT nextval('ticket_number_seq') AS n) s
$$
"""

INDEXES = ["category", "created_at", "priority", "sentiment", "status"]


def upgrade() -> None:
    # ---------------------------------------------------------------- tickets
    op.rename_table("complaints", "tickets")
    op.execute("ALTER SEQUENCE complaint_reference_seq RENAME TO ticket_number_seq")
    op.execute("ALTER SEQUENCE complaints_id_seq RENAME TO tickets_id_seq")
    op.execute(NEXT_TICKET_NUMBER)
    op.execute("ALTER TABLE tickets RENAME CONSTRAINT pk_complaints TO pk_tickets")
    op.execute("ALTER TABLE tickets RENAME CONSTRAINT uq_complaints_external_id TO uq_tickets_external_id")
    op.execute("ALTER TABLE tickets RENAME CONSTRAINT uq_complaints_reference TO uq_tickets_ticket_number")
    for col in INDEXES:
        op.execute(f"ALTER INDEX ix_complaints_{col} RENAME TO ix_tickets_{col}")
    op.execute("ALTER INDEX ix_complaints_created_category RENAME TO ix_tickets_created_category")

    op.alter_column("tickets", "reference", new_column_name="ticket_number", server_default=None)
    op.execute(
        "UPDATE tickets SET ticket_number = 'INC-' || CASE WHEN substr(ticket_number, 5)::int < 100000 "
        "THEN lpad(substr(ticket_number, 5)::int::text, 5, '0') ELSE substr(ticket_number, 5)::int::text END"
    )
    op.alter_column("tickets", "ticket_number", server_default=sa.text("next_ticket_number()"))
    op.alter_column("tickets", "text", new_column_name="description")

    op.add_column("tickets", sa.Column("description_source", sa.String(16), nullable=True))
    op.execute(
        "UPDATE tickets SET description_source = CASE WHEN text_is_template THEN 'template' "
        "WHEN source = 'dataset' THEN 'dataset_remark' ELSE 'customer' END"
    )
    op.alter_column("tickets", "description_source", nullable=False)
    op.drop_column("tickets", "text_is_template")

    op.add_column(
        "tickets", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    )
    op.add_column("tickets", sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True))
    # The dataset's issue_responded timestamp is the first response (it was stored as resolved_at before).
    op.execute("UPDATE tickets SET first_response_at = resolved_at, updated_at = resolved_at WHERE source = 'dataset'")

    # ---------------------------------------------------------------- ai_analyses
    op.rename_table("ai_insights", "ai_analyses")
    op.execute("ALTER SEQUENCE ai_insights_id_seq RENAME TO ai_analyses_id_seq")
    op.execute("ALTER TABLE ai_analyses RENAME CONSTRAINT pk_ai_insights TO pk_ai_analyses")
    op.execute("ALTER TABLE ai_analyses DROP CONSTRAINT fk_ai_insights_complaint_id_complaints")
    op.execute("ALTER INDEX ix_ai_insights_complaint_id RENAME TO ix_ai_analyses_ticket_id")
    op.alter_column("ai_analyses", "complaint_id", new_column_name="ticket_id")
    op.create_foreign_key(
        op.f("fk_ai_analyses_ticket_id_tickets"), "ai_analyses", "tickets", ["ticket_id"], ["id"], ondelete="CASCADE"
    )
    op.alter_column("ai_analyses", "recommended_actions", new_column_name="recommendations", nullable=True)
    op.alter_column("ai_analyses", "customer_reply", new_column_name="draft_response", nullable=True)
    for col in ("summary", "key_issues", "provider", "model", "prompt_version"):
        op.alter_column("ai_analyses", col, nullable=True)
    op.add_column("ai_analyses", sa.Column("kind", sa.String(16), server_default="copilot", nullable=False))
    op.alter_column("ai_analyses", "kind", server_default=None)
    op.add_column("ai_analyses", sa.Column("category", sa.String(64), nullable=True))
    op.add_column("ai_analyses", sa.Column("intent", sa.String(64), nullable=True))
    op.add_column("ai_analyses", sa.Column("sentiment", sa.String(16), nullable=True))
    op.add_column("ai_analyses", sa.Column("priority", sa.String(16), nullable=True))
    op.add_column("ai_analyses", sa.Column("entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("ai_analyses", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("ai_analyses", sa.Column("model_version", sa.String(64), nullable=True))
    # Earlier insights get the ticket's triage snapshot.
    op.execute(
        "UPDATE ai_analyses a SET category = t.category, intent = t.intent, sentiment = t.sentiment, "
        "priority = t.priority, entities = t.entities, confidence = t.category_confidence, "
        "model_version = t.model_version FROM tickets t WHERE t.id = a.ticket_id"
    )


def downgrade() -> None:
    for col in ("model_version", "confidence", "entities", "priority", "sentiment", "intent", "category", "kind"):
        op.drop_column("ai_analyses", col)
    op.execute("DELETE FROM ai_analyses WHERE summary IS NULL")
    for col in ("summary", "key_issues", "provider", "model", "prompt_version"):
        op.alter_column("ai_analyses", col, nullable=False)
    op.alter_column("ai_analyses", "draft_response", new_column_name="customer_reply", nullable=False)
    op.alter_column("ai_analyses", "recommendations", new_column_name="recommended_actions", nullable=False)
    op.drop_constraint("fk_ai_analyses_ticket_id_tickets", "ai_analyses", type_="foreignkey")
    op.alter_column("ai_analyses", "ticket_id", new_column_name="complaint_id")
    op.execute("ALTER INDEX ix_ai_analyses_ticket_id RENAME TO ix_ai_insights_complaint_id")
    op.execute("ALTER TABLE ai_analyses RENAME CONSTRAINT pk_ai_analyses TO pk_ai_insights")
    op.execute("ALTER SEQUENCE ai_analyses_id_seq RENAME TO ai_insights_id_seq")
    op.rename_table("ai_analyses", "ai_insights")

    op.execute("UPDATE tickets SET resolved_at = first_response_at WHERE source = 'dataset'")
    op.drop_column("tickets", "first_response_at")
    op.drop_column("tickets", "updated_at")
    op.add_column("tickets", sa.Column("text_is_template", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.execute("UPDATE tickets SET text_is_template = (description_source = 'template')")
    op.alter_column("tickets", "text_is_template", server_default=None)
    op.drop_column("tickets", "description_source")
    op.alter_column("tickets", "description", new_column_name="text")
    op.alter_column("tickets", "ticket_number", server_default=None)
    op.execute("UPDATE tickets SET ticket_number = 'CMP-' || lpad(substr(ticket_number, 5)::int::text, 6, '0')")
    op.alter_column("tickets", "ticket_number", new_column_name="reference")
    op.execute("DROP FUNCTION next_ticket_number()")
    op.execute("ALTER INDEX ix_tickets_created_category RENAME TO ix_complaints_created_category")
    for col in INDEXES:
        op.execute(f"ALTER INDEX ix_tickets_{col} RENAME TO ix_complaints_{col}")
    op.execute("ALTER TABLE tickets RENAME CONSTRAINT uq_tickets_ticket_number TO uq_complaints_reference")
    op.execute("ALTER TABLE tickets RENAME CONSTRAINT uq_tickets_external_id TO uq_complaints_external_id")
    op.execute("ALTER TABLE tickets RENAME CONSTRAINT pk_tickets TO pk_complaints")
    op.execute("ALTER SEQUENCE tickets_id_seq RENAME TO complaints_id_seq")
    op.execute("ALTER SEQUENCE ticket_number_seq RENAME TO complaint_reference_seq")
    op.rename_table("tickets", "complaints")
    op.alter_column(
        "complaints",
        "reference",
        server_default=sa.text("'CMP-' || lpad(nextval('complaint_reference_seq')::text, 6, '0')"),
    )
    op.create_foreign_key(
        "fk_ai_insights_complaint_id_complaints",
        "ai_insights",
        "complaints",
        ["complaint_id"],
        ["id"],
        ondelete="CASCADE",
    )
