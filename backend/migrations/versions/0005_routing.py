"""Routing: users.last_assigned_at (fair tie-break between equally loaded agents), ai_analyses.alternatives (the
classifier's top categories, shown in the review queue) and a partial index for the low-confidence review queue.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06 03:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPEN = "('NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'WAITING_CUSTOMER', 'ESCALATED')"


def upgrade() -> None:
    op.add_column("users", sa.Column("last_assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_analyses", sa.Column("alternatives", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index(
        "ix_tickets_review_queue",
        "tickets",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text(f"needs_review AND status IN {OPEN}"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tickets_review_queue", table_name="tickets", postgresql_where=sa.text(f"needs_review AND status IN {OPEN}")
    )
    op.drop_column("ai_analyses", "alternatives")
    op.drop_column("users", "last_assigned_at")
