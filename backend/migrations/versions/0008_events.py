"""Events: transactional outbox, processed_events (consumer idempotency) and dead_letters (DLQ for Admin replay).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-06 06:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=True),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox")),
    )
    op.create_index(op.f("ix_outbox_event_id"), "outbox", ["event_id"], unique=False)
    op.create_index(
        "ix_outbox_unpublished", "outbox", ["id"], unique=False, postgresql_where=sa.text("published_at IS NULL")
    )
    op.create_table(
        "processed_events",
        sa.Column("consumer", sa.String(length=48), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("consumer", "event_id", name=op.f("pk_processed_events")),
    )
    op.create_index(op.f("ix_processed_events_processed_at"), "processed_events", ["processed_at"], unique=False)
    op.create_table(
        "dead_letters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consumer", sa.String(length=48), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=True),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"], ["users.id"], name=op.f("fk_dead_letters_resolved_by_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dead_letters")),
    )
    op.create_index(op.f("ix_dead_letters_consumer"), "dead_letters", ["consumer"], unique=False)
    op.create_index(op.f("ix_dead_letters_status"), "dead_letters", ["status"], unique=False)
    op.create_index(op.f("ix_dead_letters_ticket_id"), "dead_letters", ["ticket_id"], unique=False)


def downgrade() -> None:
    op.drop_table("dead_letters")
    op.drop_table("processed_events")
    op.drop_index("ix_outbox_unpublished", table_name="outbox", postgresql_where=sa.text("published_at IS NULL"))
    op.drop_index(op.f("ix_outbox_event_id"), table_name="outbox")
    op.drop_table("outbox")
