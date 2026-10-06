"""SLA engine: sla_policies (seeded with one default per priority), sla_events, and the SLA clock on tickets.

Data:
* Imported history gets its real outcome: the clock ran from created_at to the response that closed the contact,
  against the default policy for its priority -> met / breached (so breach-rate analytics cover the dataset).
* Open tickets created in the app start their clock at created_at (paused if WAITING_CUSTOMER).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-06 07:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULTS = [  # (name, priority, target minutes) — the spec's example: a Critical ticket gets a 2-hour SLA
    ("Critical — 2 hours", "Critical", 120),
    ("High — 8 hours", "High", 480),
    ("Medium — 24 hours", "Medium", 1440),
    ("Low — 3 days", "Low", 4320),
]
OPEN = "('NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'WAITING_CUSTOMER', 'ESCALATED')"


def upgrade() -> None:
    policies = op.create_table(
        "sla_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("target_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_policies")),
    )
    op.create_index(
        "uq_sla_policies_priority_category",
        "sla_policies",
        ["priority", sa.text("coalesce(category, '*')")],
        unique=True,
    )
    op.bulk_insert(
        policies, [{"name": n, "priority": p, "category": None, "target_minutes": m} for n, p, m in DEFAULTS]
    )

    op.create_table(
        "sla_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_sla_events_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_events")),
    )
    op.create_index(op.f("ix_sla_events_ticket_id"), "sla_events", ["ticket_id"], unique=False)

    for name, type_ in (
        ("sla_policy_id", sa.Integer()),
        ("sla_target_seconds", sa.Integer()),
        ("sla_started_at", sa.DateTime(timezone=True)),
        ("sla_deadline", sa.DateTime(timezone=True)),
        ("sla_paused_at", sa.DateTime(timezone=True)),
        ("sla_stopped_at", sa.DateTime(timezone=True)),
        ("sla_warned_at", sa.DateTime(timezone=True)),
        ("sla_breached_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("tickets", sa.Column(name, type_, nullable=True))
    op.add_column("tickets", sa.Column("sla_paused_seconds", sa.Integer(), server_default="0", nullable=False))
    op.add_column("tickets", sa.Column("sla_status", sa.String(length=12), server_default="none", nullable=False))
    op.create_foreign_key(
        op.f("fk_tickets_sla_policy_id_sla_policies"),
        "tickets",
        "sla_policies",
        ["sla_policy_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_tickets_sla_due", "tickets", ["sla_deadline"], postgresql_where=sa.text("sla_status = 'running'")
    )
    op.create_index("ix_tickets_sla_status", "tickets", ["sla_status"])

    # ---------------------------------------------------------------- data
    op.execute(
        """
        UPDATE tickets t SET
            sla_policy_id = p.id,
            sla_target_seconds = p.target_minutes * 60,
            sla_started_at = t.created_at,
            sla_deadline = t.created_at + make_interval(mins => p.target_minutes),
            sla_stopped_at = coalesce(t.resolved_at, t.closed_at),
            sla_status = CASE WHEN coalesce(t.resolved_at, t.closed_at)
                                   <= t.created_at + make_interval(mins => p.target_minutes)
                              THEN 'met' ELSE 'breached' END,
            sla_breached_at = CASE WHEN coalesce(t.resolved_at, t.closed_at)
                                        > t.created_at + make_interval(mins => p.target_minutes)
                                   THEN t.created_at + make_interval(mins => p.target_minutes) END
        FROM sla_policies p
        WHERE p.priority = t.priority AND p.category IS NULL
          AND t.status IN ('RESOLVED', 'CLOSED') AND coalesce(t.resolved_at, t.closed_at) IS NOT NULL
        """
    )
    op.execute(
        f"""
        UPDATE tickets t SET
            sla_policy_id = p.id,
            sla_target_seconds = p.target_minutes * 60,
            sla_started_at = t.created_at,
            sla_deadline = t.created_at + make_interval(mins => p.target_minutes),
            sla_paused_at = CASE WHEN t.status = 'WAITING_CUSTOMER' THEN now() END,
            sla_status = CASE WHEN t.status = 'WAITING_CUSTOMER' THEN 'paused' ELSE 'running' END
        FROM sla_policies p
        WHERE p.priority = t.priority AND p.category IS NULL AND t.status IN {OPEN} AND t.status <> 'NEW'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_sla_status", table_name="tickets")
    op.drop_index("ix_tickets_sla_due", table_name="tickets", postgresql_where=sa.text("sla_status = 'running'"))
    op.drop_constraint(op.f("fk_tickets_sla_policy_id_sla_policies"), "tickets", type_="foreignkey")
    for name in (
        "sla_status",
        "sla_paused_seconds",
        "sla_breached_at",
        "sla_warned_at",
        "sla_stopped_at",
        "sla_paused_at",
        "sla_deadline",
        "sla_started_at",
        "sla_target_seconds",
        "sla_policy_id",
    ):
        op.drop_column("tickets", name)
    op.drop_index(op.f("ix_sla_events_ticket_id"), table_name="sla_events")
    op.drop_table("sla_events")
    op.drop_index("uq_sla_policies_priority_category", table_name="sla_policies")
    op.drop_table("sla_policies")
