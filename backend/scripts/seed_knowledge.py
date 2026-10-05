"""Seed the knowledge base (scripts/knowledge_seed.py) and embed every article. Idempotent: articles are matched by
title, existing ones are left as Admins edited them; articles without an embedding for the current model are
(re-)embedded.

Usage:  python -m scripts.seed_knowledge        (also run by scripts.seed)
"""

from __future__ import annotations

import asyncio

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import get_embedder
from app.core.db import SessionLocal, dispose_engine
from app.models import KnowledgeArticle
from app.services.retrieval import embed_article
from scripts.knowledge_seed import ARTICLES


async def seed_knowledge(db: AsyncSession) -> dict[str, int]:
    existing = set((await db.scalars(select(KnowledgeArticle.title))).all())
    created = 0
    for item in ARTICLES:
        if item["title"] not in existing:
            db.add(KnowledgeArticle(title=item["title"], body=item["body"], category=item["category"]))
            created += 1
    await db.flush()
    stale = (
        await db.scalars(
            select(KnowledgeArticle).where(
                or_(KnowledgeArticle.embedding.is_(None), KnowledgeArticle.embedding_model != get_embedder().name)
            )
        )
    ).all()
    for article in stale:
        await embed_article(article)
    await db.commit()
    return {"created": created, "embedded": len(stale)}


async def run() -> None:
    async with SessionLocal() as db:
        result = await seed_knowledge(db)
    await dispose_engine()
    print(f"knowledge base: {result['created']} new articles, {result['embedded']} embedded ({get_embedder().name})")


if __name__ == "__main__":
    asyncio.run(run())
