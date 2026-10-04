"""Version 1 of the HTTP API. Every route lives under /api/v1."""

from fastapi import APIRouter

from app.api.v1 import ai, analytics, meta, tickets

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
api_router.include_router(tickets.router)
api_router.include_router(ai.router)
api_router.include_router(analytics.router)
