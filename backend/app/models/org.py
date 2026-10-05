"""Organisation: departments, teams, users (Admin / Agent) and complaint categories."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

ROLES = ("ADMIN", "AGENT")


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    teams: Mapped[list[Team]] = relationship(back_populates="department", order_by="Team.name")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)  # e.g. "Payments Support"
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    department: Mapped[Department] = relationship(back_populates="teams", lazy="joined")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), unique=True)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(8), index=True)  # ADMIN | AGENT
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Imported from the dataset's Agent_name / Supervisor columns (None for users created in the app).
    source: Mapped[str] = mapped_column(String(16), default="app")  # "app" | "dataset"
    supervisor: Mapped[str | None] = mapped_column(String(160))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When a ticket was last assigned to this user (routing breaks ties between equally loaded agents with it).
    last_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    team: Mapped[Team | None] = relationship(lazy="joined")

    __table_args__ = (CheckConstraint("role IN ('ADMIN', 'AGENT')", name="role"),)

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"


class Category(Base):
    """Complaint categories (the 12 dataset categories). `team_id` is the team that owns the category — the routing
    rules send a ticket to this team."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    team: Mapped[Team | None] = relationship(lazy="joined")
