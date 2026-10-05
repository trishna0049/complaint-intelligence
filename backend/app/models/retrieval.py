"""Retrieval tables: ticket embeddings and the knowledge base (both searched by meaning and by keywords)."""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.ai.embeddings import DIM
from app.core.db import Base
from app.models.org import User


class TicketEmbedding(Base):
    """One vector per ticket and embedding model (MiniLM, 384 dims), searched with an HNSW cosine index."""

    __tablename__ = "ticket_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    embedding: Mapped[list[float]] = mapped_column(Vector(DIM))
    model_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ticket_id", "model_name", name="uq_ticket_embeddings_ticket_model"),
        Index(
            "ix_ticket_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


ARTICLE_TSV = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(body, '')), 'B')"
)


class KnowledgeArticle(Base):
    """Help articles (policies and how-tos). Admins create and edit them; everyone reads and searches them."""

    __tablename__ = "knowledge_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), unique=True)
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64), index=True)  # a ticket category, or None = general
    embedding: Mapped[list[float] | None] = mapped_column(Vector(DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    # How often the article grounded a copilot answer (incremented when the copilot cites it).
    usage_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, Computed(ARTICLE_TSV, persisted=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id], lazy="joined")

    __table_args__ = (
        Index(
            "ix_knowledge_articles_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_knowledge_articles_search", "search_vector", postgresql_using="gin"),
    )
