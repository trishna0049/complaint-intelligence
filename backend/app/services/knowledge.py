"""Knowledge base: help articles that agents read and search and the copilot is grounded in. Admins create, edit
and delete them (each change audited); the embedding is recomputed whenever the title or body changes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.priority import BASE_PRIORITY
from app.models import KnowledgeArticle, User
from app.repositories import users as users_repo
from app.schemas.knowledge import ArticleCreate, ArticleUpdate
from app.services import retrieval

SNIPPET = 220


def snippet(body: str, length: int = SNIPPET) -> str:
    flat = " ".join(body.split())
    return flat if len(flat) <= length else flat[: length - 1].rsplit(" ", 1)[0] + "…"


def _check_category(category: str | None) -> None:
    if category and category not in BASE_PRIORITY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown category")


async def get(db: AsyncSession, article_id: int) -> KnowledgeArticle:
    a = await db.get(KnowledgeArticle, article_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Article not found")
    return a


async def list_articles(
    db: AsyncSession, *, category: str | None, page: int, page_size: int
) -> tuple[list[KnowledgeArticle], int]:
    stmt = select(KnowledgeArticle)
    if category:
        stmt = stmt.where(KnowledgeArticle.category == category)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.order_by(KnowledgeArticle.category.nulls_last(), KnowledgeArticle.title)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return list(rows.unique().all()), total


def _title_taken() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, detail={"code": "conflict", "message": "An article with this title exists."}
    )


async def _save(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _title_taken() from exc


async def create(db: AsyncSession, admin: User, data: ArticleCreate) -> KnowledgeArticle:
    _check_category(data.category)
    a = KnowledgeArticle(
        title=data.title, body=data.body, category=data.category or None, created_by_id=admin.id, updated_by_id=admin.id
    )
    await retrieval.embed_article(a)
    db.add(a)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _title_taken() from exc
    users_repo.audit(
        db,
        "knowledge.create",
        actor_id=admin.id,
        resource_type="knowledge_article",
        resource_id=a.id,
        metadata={"title": a.title},
    )
    await _save(db)
    return await get(db, a.id)


async def update(db: AsyncSession, admin: User, article_id: int, data: ArticleUpdate) -> KnowledgeArticle:
    a = await get(db, article_id)
    changes: dict[str, Any] = data.model_dump(exclude_unset=True)
    for key in ("title", "body"):  # null = leave unchanged
        if changes.get(key) is None:
            changes.pop(key, None)
    if "category" in changes:  # null or "" = general article
        changes["category"] = changes["category"] or None
        _check_category(changes["category"])
    changed = {k: v for k, v in changes.items() if getattr(a, k) != v}
    if not changed:
        return a
    for key, value in changed.items():
        setattr(a, key, value)
    a.updated_by_id = admin.id
    if {"title", "body"} & changed.keys():
        await retrieval.embed_article(a)
    users_repo.audit(
        db,
        "knowledge.update",
        actor_id=admin.id,
        resource_type="knowledge_article",
        resource_id=a.id,
        metadata={"title": a.title, "fields": sorted(changed)},
    )
    await _save(db)
    await db.refresh(a)
    return await get(db, a.id)


async def delete(db: AsyncSession, admin: User, article_id: int) -> None:
    a = await get(db, article_id)
    users_repo.audit(
        db,
        "knowledge.delete",
        actor_id=admin.id,
        resource_type="knowledge_article",
        resource_id=a.id,
        metadata={"title": a.title},
    )
    await db.delete(a)
    await db.commit()
