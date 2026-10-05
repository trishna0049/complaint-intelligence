"""Knowledge base: everyone reads and searches (hybrid: meaning + keywords); Admins create, edit and delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AdminUser, CurrentUser
from app.core.db import get_session
from app.models import KnowledgeArticle
from app.schemas.common import Page
from app.schemas.knowledge import ArticleCreate, ArticleHitOut, ArticleOut, ArticleSummary, ArticleUpdate
from app.services import knowledge as svc
from app.services import retrieval
from app.services import tickets as tickets_svc

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
Db = Depends(get_session)


def summary(a: KnowledgeArticle) -> ArticleSummary:
    return ArticleSummary(
        id=a.id,
        title=a.title,
        category=a.category,
        snippet=svc.snippet(a.body),
        usage_count=a.usage_count,
        updated_at=a.updated_at,
    )


def hit_out(h: retrieval.ArticleHit) -> ArticleHitOut:
    return ArticleHitOut(
        **summary(h.article).model_dump(),
        score=round(h.hit.score, 5),
        similarity=h.hit.similarity,
        matched_by=h.hit.matched_by,
    )


@router.get("", response_model=Page[ArticleSummary])
async def list_articles(
    _: CurrentUser,
    db: AsyncSession = Db,
    category: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Page[ArticleSummary]:
    items, total = await svc.list_articles(db, category=category, page=page, page_size=page_size)
    return Page(items=[summary(a) for a in items], total=total, page=page, page_size=page_size)


@router.get("/search", response_model=list[ArticleHitOut])
async def search(
    user: CurrentUser,
    db: AsyncSession = Db,
    q: str | None = Query(default=None, max_length=500),
    ticket_id: int | None = Query(default=None, ge=1, description="Articles relevant to this ticket"),
    category: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=5, ge=1, le=20),
) -> list[ArticleHitOut]:
    """Hybrid search: by meaning (MiniLM + pgvector) and keywords (PostgreSQL full text), fused by rank."""
    if ticket_id is not None:
        t = await tickets_svc.get_ticket(db, user, ticket_id)
        return [hit_out(h) for h in await retrieval.articles_for_ticket(db, t, limit=limit)]
    return [hit_out(h) for h in await retrieval.search_articles(db, q or "", category=category, limit=limit)]


@router.get("/{article_id}", response_model=ArticleOut)
async def get_article(article_id: int, _: CurrentUser, db: AsyncSession = Db) -> ArticleOut:
    return ArticleOut.model_validate(await svc.get(db, article_id))


@router.post("", response_model=ArticleOut, status_code=status.HTTP_201_CREATED)
async def create_article(body: ArticleCreate, admin: AdminUser, db: AsyncSession = Db) -> ArticleOut:
    return ArticleOut.model_validate(await svc.create(db, admin, body))


@router.patch("/{article_id}", response_model=ArticleOut)
async def update_article(article_id: int, body: ArticleUpdate, admin: AdminUser, db: AsyncSession = Db) -> ArticleOut:
    return ArticleOut.model_validate(await svc.update(db, admin, article_id, body))


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(article_id: int, admin: AdminUser, db: AsyncSession = Db) -> None:
    await svc.delete(db, admin, article_id)
