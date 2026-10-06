"""Notifications: who is told about what (assignment, escalation, SLA warning / breach), reading them (own only),
real-time delivery (Redis pub/sub -> SSE, also over a real HTTP stream) and optional e-mail."""

from __future__ import annotations

import asyncio
import json
import socket
from datetime import timedelta

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.redis import get_redis
from app.models import Notification, Ticket, User
from app.services import notifications as svc
from app.services import sla

from .conftest import _PASSWORD_HASH, auth_headers

PAYMENTS = {"description": "I was charged twice for my order of ₹12,500 and nobody helps", "channel": "Email"}
REFUND = {"description": "refund not received yet, where is my refund"}  # a team without agents: unassigned


async def create(client, payload=PAYMENTS) -> dict:
    res = await client.post("/api/v1/tickets", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


async def inbox(user: User) -> list[Notification]:
    async with SessionLocal() as db:
        rows = await db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id))
        return list(rows.all())


async def overdue(tid: int, delta: timedelta) -> None:
    async with SessionLocal() as db:
        t = await db.get(Ticket, tid)
        t.sla_started_at -= delta
        t.sla_deadline -= delta
        await db.commit()


# ------------------------------------------------------------------------------------------------ who gets what
async def test_routing_tells_the_assignee(client, org):
    t = await create(client)
    (n,) = await inbox(org.agent)
    assert n.type == "ticket_assigned" and n.ticket_id == t["id"] and n.severity == "info"
    assert n.title == f"{t['ticket_number']} assigned to you" and n.message.startswith("Routed to you by the rules")
    assert await inbox(org.admin) == []  # the creator isn't told about their own ticket


async def test_manual_assignment_notifies_except_when_taking_it_yourself(client, agent_client, org):
    async with SessionLocal() as db:
        mate = User(
            name="Tara Teammate",
            email="tara@test.example",
            password_hash=_PASSWORD_HASH,
            role="AGENT",
            team_id=org.teams["Payments Support"].id,
        )
        db.add(mate)
        await db.commit()
    tid = (await create(client))["id"]  # -> Arjun (rules)
    await agent_client.post(f"/api/v1/tickets/{tid}/assign", json={"assignee_id": mate.id})
    (n,) = await inbox(mate)
    assert n.message.startswith("Assigned to you by Arjun Agent")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=__import__("app.main").main.app),
        base_url="http://test",
        headers=auth_headers(mate),
    ) as tara:
        await tara.post(f"/api/v1/tickets/{tid}/assign", json={"assignee_id": mate.id, "note": "again"})
    assert len(await inbox(mate)) == 1  # no-op reassignment, and no self-notification


async def test_escalation_alerts_the_admins(client, agent_client, org):
    tid = (await create(client))["id"]
    await agent_client.post(f"/api/v1/tickets/{tid}/escalate", json={"reason": "Customer threatens legal action"})
    (n,) = [x for x in await inbox(org.admin) if x.type == "ticket_escalated"]
    assert n.severity == "warning" and "Escalated by Arjun Agent: Customer threatens legal action" in n.message
    tid2 = (await create(client))["id"]
    await client.post(f"/api/v1/tickets/{tid2}/escalate", json={"reason": "I'll take it from here"})
    assert len([x for x in await inbox(org.admin) if x.type == "ticket_escalated"]) == 1  # not told about own action


async def test_sla_warning_goes_to_the_assignee_and_a_breach_to_the_admins(client, org):
    tid = (await create(client))["id"]  # Critical, Arjun
    await overdue(tid, timedelta(minutes=100))
    await sla.scan_once()
    (warn,) = [n for n in await inbox(org.agent) if n.type == "sla_warning"]
    assert warn.severity == "warning" and warn.title.startswith("SLA at risk: INC-") and "due" in warn.message
    assert not [n for n in await inbox(org.admin) if n.type == "sla_warning"]

    await overdue(tid, timedelta(minutes=30))
    await sla.scan_once()
    admin_types = sorted(n.type for n in await inbox(org.admin))
    assert admin_types == ["sla_breached", "ticket_escalated"]  # the breach, and the automatic escalation it caused
    escalated = next(n for n in await inbox(org.admin) if n.type == "ticket_escalated")
    assert escalated.severity == "critical" and "Escalated by the SLA engine" in escalated.message
    breach = next(n for n in await inbox(org.agent) if n.type == "sla_breached")
    assert breach.severity == "critical"


async def test_unassigned_sla_warnings_go_to_the_admins_and_inactive_admins_get_nothing(client, org):
    async with SessionLocal() as db:
        db.add(
            User(
                name="Old Admin", email="old@test.example", password_hash=_PASSWORD_HASH, role="ADMIN", is_active=False
            )
        )
        await db.commit()
    tid = (await create(client, REFUND))["id"]
    await overdue(tid, timedelta(days=2, hours=22))  # High? Medium? push it past 80 % of any default target
    await sla.scan_once()
    assert any(n.type == "sla_warning" for n in await inbox(org.admin))
    async with SessionLocal() as db:
        old = await db.scalar(select(User).where(User.email == "old@test.example"))
    assert await inbox(old) == []


# ------------------------------------------------------------------------------------------------ reading
async def test_list_read_and_read_all_are_per_user(client, agent_client, other_agent_client, org):
    await create(client)
    await create(client)
    page = (await agent_client.get("/api/v1/notifications")).json()
    assert page["total"] == 2 and page["unread"] == 2 and page["items"][0]["type"] == "ticket_assigned"
    first = page["items"][0]["id"]
    assert (await other_agent_client.post(f"/api/v1/notifications/{first}/read")).status_code == 404
    assert (await other_agent_client.get("/api/v1/notifications")).json()["total"] == 0
    res = await agent_client.post(f"/api/v1/notifications/{first}/read")
    assert res.status_code == 200 and res.json()["read_at"]
    unread = (await agent_client.get("/api/v1/notifications", params={"unread": "true"})).json()
    assert unread["total"] == 1 and unread["unread"] == 1
    assert (await agent_client.post("/api/v1/notifications/read-all")).json() == {"marked": 1}
    assert (await agent_client.get("/api/v1/notifications")).json()["unread"] == 0


async def test_email_preference(agent_client, org):
    assert (await agent_client.get("/api/v1/notifications/preferences")).json() == {"email": True}
    assert (await agent_client.put("/api/v1/notifications/preferences", json={"email": False})).json() == {
        "email": False
    }
    assert (await agent_client.get("/api/v1/auth/me")).json()["email_notifications"] is False


# ------------------------------------------------------------------------------------------------ real time
async def test_new_notifications_are_published_to_the_users_channel(client, org):
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(svc.user_channel(org.agent.id))
    await pubsub.get_message(timeout=1)  # subscribe confirmation
    t = await create(client)
    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5)
    await pubsub.aclose()
    payload = json.loads(msg["data"])
    assert payload["kind"] == "notification" and payload["notification"]["ticket_id"] == t["id"]


async def test_sse_stream_sends_ready_then_live_events(org):
    gen = svc.stream(org.agent, unread=3)
    assert await anext(gen) == 'event: ready\ndata: {"unread": 3}\n\n'
    nxt = asyncio.ensure_future(anext(gen))
    await asyncio.sleep(0.2)  # the stream is now waiting on Redis
    await get_redis().publish(svc.user_channel(org.agent.id), json.dumps({"kind": "unread", "unread": 0}))
    assert await asyncio.wait_for(nxt, 5) == 'event: unread\ndata: {"unread": 0}\n\n'
    await gen.aclose()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_sse_over_real_http_with_the_bearer_header(client, org):
    """A real server (uvicorn), a real streaming response: the access token goes in the Authorization header."""
    import uvicorn

    from app.main import app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(50):
            if server.started:
                break
            await asyncio.sleep(0.1)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10) as http:
            assert (await http.get("/api/v1/notifications/stream")).status_code == 401
            async with http.stream("GET", "/api/v1/notifications/stream", headers=auth_headers(org.agent)) as res:
                assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
                lines = res.aiter_lines()
                assert await anext(lines) == "event: ready"
                assert json.loads((await anext(lines)).removeprefix("data: ")) == {"unread": 0}
                await create(client)  # routed to Arjun -> notification on his stream
                seen = []
                async for line in lines:
                    seen.append(line)
                    if line.startswith('data: {"id"'):
                        break
                assert "event: notification" in seen and "assigned to you" in seen[-1]
    finally:
        server.should_exit = True
        await task


# ------------------------------------------------------------------------------------------------ e-mail
async def test_alerts_are_emailed_when_smtp_is_configured(client, agent_client, org, monkeypatch):
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.test")
    monkeypatch.setattr(svc, "_send", lambda to, subject, body: sent.append((to, subject, body)))
    await agent_client.put("/api/v1/notifications/preferences", json={"email": False})  # Arjun opts out
    tid = (await create(client))["id"]
    await agent_client.post(f"/api/v1/tickets/{tid}/escalate", json={"reason": "Legal threat"})
    assert [(to, subject) for to, subject, _ in sent] == [("admin@test.example", f"INC-{tid:05d} escalated")]
    assert f"/tickets/{tid}" in sent[0][2]  # link back to the ticket
    (n,) = [x for x in await inbox(org.admin) if x.type == "ticket_escalated"]
    assert n.emailed_at is not None and n.email_error is None
    assert all(x.emailed_at is None for x in await inbox(org.agent))  # assignments aren't e-mailed; he opted out anyway


async def test_a_failed_email_is_recorded_and_never_loses_the_notification(client, agent_client, org, monkeypatch):
    def broken(to, subject, body):
        raise ConnectionRefusedError("SMTP down")

    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.test")
    monkeypatch.setattr(svc, "_send", broken)
    tid = (await create(client))["id"]
    await agent_client.post(f"/api/v1/tickets/{tid}/escalate", json={"reason": "Legal threat"})
    (n,) = [x for x in await inbox(org.admin) if x.type == "ticket_escalated"]
    assert n.emailed_at is None and "SMTP down" in n.email_error


async def test_sse_heartbeat_only_after_the_interval(org, monkeypatch):
    monkeypatch.setattr(get_settings(), "sse_heartbeat_seconds", 0.3)
    gen = svc.stream(org.agent, unread=0)
    await anext(gen)  # ready
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await asyncio.wait_for(anext(gen), 3) == svc.KEEPALIVE
    assert loop.time() - started >= 0.25  # not immediately after "ready"
    await gen.aclose()
