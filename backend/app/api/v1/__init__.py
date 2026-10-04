"""Version 1 of the HTTP API. Every route lives under /api/v1."""

from fastapi import APIRouter

from app.api.v1 import admin, ai, analytics, auth, meta, tickets

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(tickets.router)
api_router.include_router(ai.router)
api_router.include_router(analytics.router)
for _r in (admin.users, admin.teams, admin.departments, admin.categories, admin.audit):
    api_router.include_router(_r)

# Routes that work without signing in. Everything else requires a valid access token (enforced by a test).
PUBLIC_ROUTES = {
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
}
