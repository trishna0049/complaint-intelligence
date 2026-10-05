"""Ticket lifecycle: 8 states, assignment, customers, comments, events (timeline), attachments.

Existing rows: imported history was resolved and surveyed, so it becomes CLOSED; tickets created in the app map
Open -> TRIAGED, In Progress -> IN_PROGRESS, Resolved -> RESOLVED. Teams are filled from the category's owning team.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05 04:54:59.554109
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS customer_code_seq START 1")
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "customer_code",
            sa.String(length=16),
            server_default=sa.text("'CUS-' || lpad(nextval('customer_code_seq')::text, 5, '0')"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("segment", sa.String(length=32), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("customer_code", name=op.f("uq_customers_customer_code")),
    )
    op.create_table(
        "ticket_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_attachments_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_ticket_attachments_uploaded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_attachments")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_ticket_attachments_storage_key")),
    )
    op.create_index(op.f("ix_ticket_attachments_ticket_id"), "ticket_attachments", ["ticket_id"], unique=False)
    op.create_table(
        "ticket_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("ai_assisted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_ticket_comments_author_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_comments_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_comments")),
    )
    op.create_index(op.f("ix_ticket_comments_ticket_id"), "ticket_comments", ["ticket_id"], unique=False)
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_ticket_events_actor_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_events_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_events")),
    )
    op.create_index("ix_ticket_events_ticket_created", "ticket_events", ["ticket_id", "created_at"], unique=False)
    op.add_column("tickets", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("created_by_id", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("assignee_id", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("team_id", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("resolution", sa.Text(), nullable=True))
    op.add_column("tickets", sa.Column("reopen_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("tickets", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tickets_assignee_status", "tickets", ["assignee_id", "status"], unique=False)
    op.create_index("ix_tickets_created_by_id", "tickets", ["created_by_id"], unique=False)
    op.create_index(op.f("ix_tickets_customer_id"), "tickets", ["customer_id"], unique=False)
    op.create_index("ix_tickets_team_status", "tickets", ["team_id", "status"], unique=False)
    op.create_foreign_key(
        op.f("fk_tickets_created_by_id_users"), "tickets", "users", ["created_by_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        op.f("fk_tickets_team_id_teams"), "tickets", "teams", ["team_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        op.f("fk_tickets_assignee_id_users"), "tickets", "users", ["assignee_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        op.f("fk_tickets_customer_id_customers"), "tickets", "customers", ["customer_id"], ["id"], ondelete="SET NULL"
    )

    # ---------------------------------------------------------------- data
    op.execute(
        "UPDATE tickets SET status = CASE "
        "WHEN source = 'dataset' AND status = 'Resolved' THEN 'CLOSED' "
        "WHEN status = 'Open' THEN 'TRIAGED' "
        "WHEN status = 'In Progress' THEN 'IN_PROGRESS' "
        "WHEN status = 'Resolved' THEN 'RESOLVED' ELSE status END"
    )
    op.execute("UPDATE tickets SET closed_at = resolved_at WHERE status = 'CLOSED'")
    op.execute(
        "UPDATE tickets t SET team_id = c.team_id FROM categories c WHERE c.name = t.category AND t.team_id IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE tickets SET status = CASE WHEN status IN ('RESOLVED', 'CLOSED') THEN 'Resolved' "
        "WHEN status IN ('IN_PROGRESS', 'WAITING_CUSTOMER', 'ESCALATED') THEN 'In Progress' ELSE 'Open' END"
    )
    op.drop_constraint(op.f("fk_tickets_customer_id_customers"), "tickets", type_="foreignkey")
    op.drop_constraint(op.f("fk_tickets_assignee_id_users"), "tickets", type_="foreignkey")
    op.drop_constraint(op.f("fk_tickets_team_id_teams"), "tickets", type_="foreignkey")
    op.drop_constraint(op.f("fk_tickets_created_by_id_users"), "tickets", type_="foreignkey")
    op.drop_index("ix_tickets_team_status", table_name="tickets")
    op.drop_index(op.f("ix_tickets_customer_id"), table_name="tickets")
    op.drop_index("ix_tickets_created_by_id", table_name="tickets")
    op.drop_index("ix_tickets_assignee_status", table_name="tickets")
    op.drop_column("tickets", "closed_at")
    op.drop_column("tickets", "escalated_at")
    op.drop_column("tickets", "reopen_count")
    op.drop_column("tickets", "resolution")
    op.drop_column("tickets", "team_id")
    op.drop_column("tickets", "assignee_id")
    op.drop_column("tickets", "created_by_id")
    op.drop_column("tickets", "customer_id")
    op.drop_index("ix_ticket_events_ticket_created", table_name="ticket_events")
    op.drop_table("ticket_events")
    op.drop_index(op.f("ix_ticket_comments_ticket_id"), table_name="ticket_comments")
    op.drop_table("ticket_comments")
    op.drop_index(op.f("ix_ticket_attachments_ticket_id"), table_name="ticket_attachments")
    op.drop_table("ticket_attachments")
    op.drop_table("customers")
    op.execute("DROP SEQUENCE IF EXISTS customer_code_seq")
