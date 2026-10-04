"""Authentication, refresh-token rotation and reuse detection, role guards and admin management."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.api.v1 import PUBLIC_ROUTES
from app.auth.dependencies import current_user, require_admin
from app.auth.security import create_access_token
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.models import AuditLog, RefreshToken, User
from scripts.seed import allocate_supervisors, email_for

from .conftest import PASSWORD, _client, auth_headers

COOKIE = "ci_refresh"


async def login(anon: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await anon.post("/api/v1/auth/login", json={"email": email, "password": password})


async def audit_actions() -> list[str]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuditLog.action).order_by(AuditLog.id))).all())


# ------------------------------------------------------------------------------------------------ login
async def test_login_returns_access_token_and_httponly_refresh_cookie(anon, org):
    res = await login(anon, "ADMIN@test.example ")  # case and whitespace insensitive
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 15 * 60
    assert body["user"]["email"] == "admin@test.example" and body["user"]["role"] == "ADMIN"
    cookie = res.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=") and "HttpOnly" in cookie and "Path=/api/v1/auth" in cookie
    assert "samesite=strict" in cookie.lower()
    me = await anon.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["name"] == "Ada Admin"
    assert "auth.login" in await audit_actions()


async def test_login_failures_are_indistinguishable(anon, org):
    wrong = await login(anon, "admin@test.example", "nope-nope-nope")
    unknown = await login(anon, "nobody@test.example")
    assert wrong.status_code == unknown.status_code == 401
    assert (
        wrong.json()
        == unknown.json()
        == {"detail": {"code": "invalid_credentials", "message": "Invalid email or password."}}
    )
    assert (await audit_actions()).count("auth.login_failed") == 2


async def test_inactive_user_cannot_log_in(anon, org):
    async with SessionLocal() as db:
        (await db.get(User, org.agent.id)).is_active = False
        await db.commit()
    assert (await login(anon, "agent@test.example")).status_code == 401


# ------------------------------------------------------------------------------------------------ tokens
async def test_expired_and_tampered_access_tokens_are_rejected(anon, org):
    old, _ = create_access_token(org.admin.id, "ADMIN", now=datetime.now(UTC) - timedelta(hours=1))
    res = await anon.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old}"})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "token_expired"

    forged = jwt.encode(
        {"sub": str(org.agent.id), "role": "ADMIN", "type": "access", "iat": 0, "exp": 9999999999},
        "not-the-secret",
        algorithm="HS256",
    )
    res = await anon.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "invalid_token"
    assert (await anon.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"})).status_code == 401


async def test_role_comes_from_the_database_not_the_token(org):
    # A token minted while the user was ADMIN must not keep admin rights after a demotion.
    token, _ = create_access_token(org.agent.id, "ADMIN")
    async with _client({"Authorization": f"Bearer {token}"}) as c:
        assert (await c.get("/api/v1/users")).status_code == 403


async def test_refresh_rotates_the_token(anon, org):
    first = (await login(anon, "agent@test.example")).cookies[COOKIE]
    res = await anon.post("/api/v1/auth/refresh")
    assert res.status_code == 200 and res.json()["user"]["email"] == "agent@test.example"
    second = res.cookies[COOKIE]
    assert second != first
    async with SessionLocal() as db:
        tokens = (await db.scalars(select(RefreshToken).order_by(RefreshToken.id))).all()
    assert [t.revoked for t in tokens] == [True, False]
    assert tokens[0].revoked_reason == "rotated" and tokens[0].replaced_by_id == tokens[1].id
    assert tokens[0].family_id == tokens[1].family_id
    assert all(re.fullmatch(r"[0-9a-f]{64}", t.token_hash) for t in tokens)  # only hashes are stored


async def test_reusing_a_rotated_token_revokes_the_whole_family(anon, org):
    stolen = (await login(anon, "agent@test.example")).cookies[COOKIE]
    await anon.post("/api/v1/auth/refresh")  # legitimate rotation
    async with SessionLocal() as db:  # pretend the rotation happened a minute ago (outside the race leeway)
        for t in (await db.scalars(select(RefreshToken).where(RefreshToken.revoked.is_(True)))).all():
            t.revoked_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

    async with _client() as attacker:
        attacker.cookies.set(COOKIE, stolen, path="/api/v1/auth")
        res = await attacker.post("/api/v1/auth/refresh")
    assert res.status_code == 401 and res.json()["detail"]["code"] == "refresh_token_reused"
    # The legitimate client's newer token was revoked too: the login is over everywhere.
    res = await anon.post("/api/v1/auth/refresh")
    assert res.status_code == 401
    async with SessionLocal() as db:
        assert all(t.revoked for t in (await db.scalars(select(RefreshToken))).all())
    assert "auth.refresh_reuse_detected" in await audit_actions()


async def test_concurrent_refresh_within_leeway_is_a_retryable_409(anon, org):
    old = (await login(anon, "agent@test.example")).cookies[COOKIE]
    await anon.post("/api/v1/auth/refresh")
    async with _client() as other_tab:
        other_tab.cookies.set(COOKIE, old, path="/api/v1/auth")
        res = await other_tab.post("/api/v1/auth/refresh")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "refresh_race"
    assert (await anon.post("/api/v1/auth/refresh")).status_code == 200  # the session survives


async def test_expired_refresh_token(anon, org):
    await login(anon, "agent@test.example")
    async with SessionLocal() as db:
        for t in (await db.scalars(select(RefreshToken))).all():
            t.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    res = await anon.post("/api/v1/auth/refresh")
    assert res.status_code == 401 and res.json()["detail"]["code"] == "refresh_token_expired"


async def test_logout_revokes_and_clears_cookie(anon, org):
    await login(anon, "agent@test.example")
    res = await anon.post("/api/v1/auth/logout")
    assert res.status_code == 204 and f'{COOKIE}=""' in res.headers["set-cookie"]
    async with SessionLocal() as db:
        assert all(t.revoked_reason == "logout" for t in (await db.scalars(select(RefreshToken))).all())
    assert (await anon.post("/api/v1/auth/refresh")).status_code == 401
    assert (await anon.post("/api/v1/auth/logout")).status_code == 204  # idempotent


async def test_refresh_without_cookie(anon):
    res = await anon.post("/api/v1/auth/refresh")
    assert res.status_code == 401 and res.json()["detail"]["code"] == "no_refresh_token"


# ------------------------------------------------------------------------------------------------ route guards
@dataclass
class RouteInfo:
    path: str
    methods: set[str]
    dependant: Any


def api_routes() -> list[RouteInfo]:
    """Every route under /api/, flattened (FastAPI >= 0.140 wraps included routers lazily)."""
    out: list[RouteInfo] = []
    for r in app.routes:
        if isinstance(r, APIRoute):
            out.append(RouteInfo(r.path, set(r.methods), r.dependant))
        elif hasattr(r, "effective_route_contexts"):
            out.extend(RouteInfo(c.path, set(c.methods), c.dependant) for c in r.effective_route_contexts())
    return [r for r in out if r.path.startswith("/api/")]


def dependency_calls(route: RouteInfo) -> set[object]:
    seen: set[object] = set()

    def walk(dep) -> None:  # type: ignore[no-untyped-def]
        for sub in dep.dependencies:
            seen.add(sub.call)
            walk(sub)

    walk(route.dependant)
    return seen


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_non_public_route_depends_on_current_user():
    """Structural check: fails the moment someone adds a route without authentication."""
    missing = [
        f"{m} {r.path}"
        for r in api_routes()
        for m in r.methods
        if (m, r.path) not in PUBLIC_ROUTES and current_user not in dependency_calls(r)
    ]
    assert missing == [], f"routes without authentication: {missing}"
    assert len(api_routes()) > 20


async def test_every_non_public_route_returns_401_without_a_token(anon):
    """Behavioural check: an anonymous call to every protected route is rejected before anything else runs."""
    for r in api_routes():
        for m in r.methods:
            if (m, r.path) in PUBLIC_ROUTES:
                continue
            res = await anon.request(m, concrete(r.path), json={})
            assert res.status_code == 401, f"{m} {r.path} -> {res.status_code}"


async def test_public_routes_work_without_a_token(anon):
    assert (await anon.get("/api/v1/health")).status_code == 200


async def test_admin_only_routes_reject_agents_with_403(agent_client):
    admin_routes = [(m, r.path) for r in api_routes() for m in r.methods if require_admin in dependency_calls(r)]
    expected = {
        ("GET", "/api/v1/users"),
        ("POST", "/api/v1/users"),
        ("GET", "/api/v1/users/{user_id}"),
        ("PATCH", "/api/v1/users/{user_id}"),
        ("DELETE", "/api/v1/users/{user_id}"),
        ("POST", "/api/v1/teams"),
        ("PATCH", "/api/v1/teams/{team_id}"),
        ("DELETE", "/api/v1/teams/{team_id}"),
        ("GET", "/api/v1/departments"),
        ("POST", "/api/v1/departments"),
        ("POST", "/api/v1/categories"),
        ("PATCH", "/api/v1/categories/{category_id}"),
        ("DELETE", "/api/v1/categories/{category_id}"),
        ("GET", "/api/v1/analytics/overview"),
        ("GET", "/api/v1/analytics/trends"),
        ("GET", "/api/v1/analytics/categories"),
        ("GET", "/api/v1/analytics/emerging"),
        ("GET", "/api/v1/admin/audit-logs"),
    }
    assert expected <= set(admin_routes)
    for m, path in admin_routes:
        res = await agent_client.request(m, concrete(path), json={})
        assert res.status_code == 403, f"{m} {path} -> {res.status_code}"


async def test_agents_can_use_tickets_ai_and_read_reference_data(agent_client):
    assert (await agent_client.get("/api/v1/tickets")).status_code == 200
    res = await agent_client.post("/api/v1/ai/analyze", json={"description": "refund not received"})
    assert res.status_code == 200
    cats = (await agent_client.get("/api/v1/categories")).json()
    assert len(cats) == 12 and {"name", "team", "base_priority"} <= cats[0].keys()
    assert len((await agent_client.get("/api/v1/teams")).json()) == 12


# ------------------------------------------------------------------------------------------------ user admin
async def test_admin_creates_and_lists_users(client, org):
    team_id = org.teams["Refunds Desk"].id
    res = await client.post(
        "/api/v1/users",
        json={
            "name": "New Person",
            "email": "New.Person@Test.example",
            "password": "Sturdy-pass-123",
            "role": "AGENT",
            "team_id": team_id,
        },
    )
    assert res.status_code == 201, res.text
    u = res.json()
    assert u["email"] == "new.person@test.example" and u["team"]["name"] == "Refunds Desk" and u["source"] == "app"
    dup = await client.post(
        "/api/v1/users", json={"name": "Again", "email": "new.person@test.example", "password": "Sturdy-pass-123"}
    )
    assert dup.status_code == 409
    weak = await client.post("/api/v1/users", json={"name": "Weak", "email": "weak@test.example", "password": "short"})
    assert weak.status_code == 422
    bad_team = await client.post(
        "/api/v1/users", json={"name": "T", "email": "t@test.example", "password": "Sturdy-pass-123", "team_id": 999}
    )
    assert bad_team.status_code == 422
    page = (await client.get("/api/v1/users", params={"role": "AGENT", "q": "new"})).json()
    assert page["total"] == 1 and page["items"][0]["name"] == "New Person"
    assert (
        await login(
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"),
            "new.person@test.example",
            "Sturdy-pass-123",
        )
    ).status_code == 200
    assert "user.create" in await audit_actions()


async def test_deactivation_takes_effect_immediately(client, agent_client, org):
    assert (await agent_client.get("/api/v1/tickets")).status_code == 200
    res = await client.delete(f"/api/v1/users/{org.agent.id}")
    assert res.status_code == 200 and res.json()["is_active"] is False
    res = await agent_client.get("/api/v1/tickets")  # same, still unexpired access token
    assert res.status_code == 401 and res.json()["detail"]["code"] == "inactive_account"
    assert "user.deactivate" in await audit_actions()


async def test_role_change_revokes_sessions_and_last_admin_is_protected(client, anon, org):
    await login(anon, "agent@test.example")
    res = await client.patch(f"/api/v1/users/{org.agent.id}", json={"role": "ADMIN"})
    assert res.status_code == 200 and res.json()["role"] == "ADMIN"
    assert (await anon.post("/api/v1/auth/refresh")).status_code == 401  # old session ended
    # Now there are two admins; demote the agent back, then try to remove the last admin.
    await client.patch(f"/api/v1/users/{org.agent.id}", json={"role": "AGENT"})
    res = await client.patch(f"/api/v1/users/{org.admin.id}", json={"role": "AGENT"})
    assert res.status_code == 409 and "one active admin" in res.json()["detail"]["message"]
    assert (await client.delete(f"/api/v1/users/{org.admin.id}")).status_code == 409


async def test_password_reset_and_team_change(client, anon, org):
    res = await client.patch(
        f"/api/v1/users/{org.agent.id}", json={"password": "Brand-new-pass-9", "team_id": org.teams["Refunds Desk"].id}
    )
    assert res.status_code == 200 and res.json()["team"]["name"] == "Refunds Desk"
    assert (await login(anon, "agent@test.example")).status_code == 401
    assert (await login(anon, "agent@test.example", "Brand-new-pass-9")).status_code == 200
    res = await client.patch(f"/api/v1/users/{org.agent.id}", json={"clear_team": True})
    assert res.json()["team"] is None


# ------------------------------------------------------------------------------------------------ teams & categories
async def test_team_crud(client, org):
    depts = (await client.get("/api/v1/departments")).json()
    assert [d["name"] for d in depts] == ["Customer Experience", "Finance Operations", "Order Fulfilment"]
    teams = {t["name"]: t for t in (await client.get("/api/v1/teams")).json()}
    assert teams["Payments Support"]["member_count"] == 1
    assert teams["Payments Support"]["categories"] == ["Payments related"]
    res = await client.post("/api/v1/teams", json={"name": "Escalations Desk", "department_id": depts[0]["id"]})
    assert res.status_code == 201 and res.json()["member_count"] == 0
    tid = res.json()["id"]
    assert (
        await client.post("/api/v1/teams", json={"name": "escalations desk", "department_id": depts[0]["id"]})
    ).status_code == 409
    res = await client.patch(f"/api/v1/teams/{tid}", json={"name": "Escalation Desk", "description": "Tier 2"})
    assert res.json()["name"] == "Escalation Desk"
    blocked = await client.delete(f"/api/v1/teams/{teams['Payments Support']['id']}")
    assert blocked.status_code == 409  # has members and a category
    assert (await client.delete(f"/api/v1/teams/{tid}")).status_code == 204
    assert {"team.create", "team.update", "team.delete"} <= set(await audit_actions())


async def test_category_crud(client, agent_client, org):
    res = await client.post("/api/v1/categories", json={"name": "Warranty", "team_id": org.teams["Product Help"].id})
    assert res.status_code == 201 and res.json()["team"]["name"] == "Product Help"
    cid = res.json()["id"]
    assert res.json()["base_priority"] == "Medium"  # categories without a documented rule default to Medium
    res = await client.patch(f"/api/v1/categories/{cid}", json={"clear_team": True, "description": "Warranty claims"})
    assert res.json()["team"] is None and res.json()["description"] == "Warranty claims"
    assert (await agent_client.post("/api/v1/categories", json={"name": "X"})).status_code == 403
    builtin = next(c for c in (await client.get("/api/v1/categories")).json() if c["name"] == "Payments related")
    assert builtin["builtin"] is True and builtin["base_priority"] == "High"
    rename = await client.patch(f"/api/v1/categories/{builtin['id']}", json={"name": "Payments"})
    assert rename.status_code == 409 and "built-in" in rename.json()["detail"]["message"]
    assert (await client.delete(f"/api/v1/categories/{builtin['id']}")).status_code == 409
    moved = await client.patch(f"/api/v1/categories/{builtin['id']}", json={"team_id": org.teams["Refunds Desk"].id})
    assert moved.status_code == 200 and moved.json()["team"]["name"] == "Refunds Desk"  # ownership can change
    assert (await client.delete(f"/api/v1/categories/{cid}")).status_code == 204
    logs = (await client.get("/api/v1/admin/audit-logs")).json()
    assert logs[0]["action"] == "category.delete" and logs[0]["actor_id"] == org.admin.id


# ------------------------------------------------------------------------------------------------ seeding
def test_supervisor_groups_are_allocated_in_proportion_to_volume():
    supervisors = [f"S{i:02d}" for i in range(40)]
    volume = {"Big": 900, "Mid": 80, "Small": 15, "Tiny": 5}
    alloc = allocate_supervisors(supervisors, volume)
    counts = {c: list(alloc.values()).count(c) for c in volume}
    assert counts == {"Big": 33, "Mid": 4, "Small": 2, "Tiny": 1}  # 36 spare seats by largest remainder, +1 each
    assert alloc == allocate_supervisors(list(reversed(supervisors)), volume)  # deterministic
    with pytest.raises(ValueError):
        allocate_supervisors(["only-one"], volume)


def test_seeded_emails_are_unique_and_ascii():
    taken: set[str] = set()
    assert email_for("José O'Neil", taken) == "jose.o.neil@shopzilla.example"
    assert email_for("Jose O Neil", taken) == "jose.o.neil2@shopzilla.example"


def test_production_refuses_the_development_jwt_secret():
    s = get_settings().model_copy(update={"environment": "production"})
    with pytest.raises(RuntimeError):
        s.check_production()
    s.model_copy(update={"jwt_secret": "x" * 40}).check_production()


async def test_other_agent_fixture_is_in_another_team(org):
    assert org.agent.team_id != org.other_agent.team_id
    assert auth_headers(org.other_agent)["Authorization"].startswith("Bearer ")
