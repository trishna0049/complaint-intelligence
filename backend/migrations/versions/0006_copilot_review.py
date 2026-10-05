"""Copilot completion: root cause and the human review of each draft reply (pending / accepted / discarded /
superseded), with who reviewed it, the text actually posted, whether it was edited and the resulting comment.

Existing copilot rows: the newest per ticket becomes `pending`, older ones `superseded`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-06 04:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_analyses", sa.Column("root_cause", sa.Text(), nullable=True))
    op.add_column("ai_analyses", sa.Column("draft_status", sa.String(length=12), nullable=True))
    op.add_column("ai_analyses", sa.Column("reviewed_by_id", sa.Integer(), nullable=True))
    op.add_column("ai_analyses", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_analyses", sa.Column("final_response", sa.Text(), nullable=True))
    op.add_column("ai_analyses", sa.Column("edited", sa.Boolean(), nullable=True))
    op.add_column("ai_analyses", sa.Column("comment_id", sa.Integer(), nullable=True))
    op.add_column("ai_analyses", sa.Column("discard_reason", sa.String(length=500), nullable=True))
    op.create_foreign_key(
        op.f("fk_ai_analyses_reviewed_by_id_users"),
        "ai_analyses",
        "users",
        ["reviewed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_ai_analyses_comment_id_ticket_comments"),
        "ai_analyses",
        "ticket_comments",
        ["comment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "UPDATE ai_analyses a SET draft_status = CASE WHEN a.id = latest.id THEN 'pending' ELSE 'superseded' END "
        "FROM (SELECT DISTINCT ON (ticket_id) ticket_id, id FROM ai_analyses WHERE kind = 'copilot' "
        "ORDER BY ticket_id, id DESC) latest WHERE a.kind = 'copilot' AND a.ticket_id = latest.ticket_id"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_ai_analyses_comment_id_ticket_comments"), "ai_analyses", type_="foreignkey")
    op.drop_constraint(op.f("fk_ai_analyses_reviewed_by_id_users"), "ai_analyses", type_="foreignkey")
    for column in (
        "discard_reason",
        "comment_id",
        "edited",
        "final_response",
        "reviewed_at",
        "reviewed_by_id",
        "draft_status",
        "root_cause",
    ):
        op.drop_column("ai_analyses", column)
