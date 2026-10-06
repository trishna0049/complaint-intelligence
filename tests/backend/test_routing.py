"""Routing: the pure rules (category -> team -> least-busy agent, review queue, capacity), and the service through the
API — on creation, after a category is confirmed or corrected, Admin auto-assign, and two tickets at once."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.domain.routing import Candidate, Outcome, Rule, decide, least_busy
from app.models import AuditLog, Ticket, User

from .conftest import _PASSWORD_HASH, _client, auth_headers

PAYMENTS = {"description": "I was charged twice for my order of ₹12,500 and nobody helps", "channel": "Email"}
RETURNS = {"description": "want to return damaged item please pick up"}
REFUND = {"description": "refund not received yet, where is my refund"}
T0 = datetime(2026, 10, 1, tzinfo=UTC)


# ------------------------------------------------------------------------------------------------ rules (unit)
def rules(**kw):
    base = {
        "category": "Payments related",
        "needs_review": False,
        "confidence": 0.9,
        "team_id": 3,
        "team_name": "Payments Support",
        "candidates": [Candidate(1, "A", 4), Candidate(2, "B", 1), Candidate(3, "C", 7)],
        "max_open": 25,
    }
    return decide(**{**base, **kw})


def test_least_busy_agent_of_the_owning_team():
    d = rules()
    assert (d.outcome, d.rule, d.team_id, d.assignee_id) == (Outcome.ASSIGNED, Rule.LEAST_BUSY, 3, 2)
    assert d.candidates == 3 and d.available == 3
    assert "Least busy of 3 available agents in Payments Support (1 open)" in d.reason


def test_low_confidence_goes_to_the_review_queue_before_anything_else():
    d = rules(needs_review=True, confidence=0.31)
    assert (d.outcome, d.rule, d.team_id, d.assignee) == (Outcome.REVIEW, Rule.REVIEW, None, None)
    assert "31%" in d.reason


def test_category_without_a_team_is_unrouted():
    d = rules(team_id=None, team_name=None)
    assert (d.outcome, d.rule, d.assignee) == (Outcome.UNROUTED, Rule.NO_TEAM, None)


def test_team_without_agents_and_team_at_capacity_wait_in_the_team_queue():
    d = rules(candidates=[])
    assert (d.outcome, d.rule, d.team_id) == (Outcome.TEAM_QUEUE, Rule.NO_AGENTS, 3)
    d = rules(max_open=4, candidates=[Candidate(1, "A", 4), Candidate(2, "B", 9)])
    assert (d.outcome, d.rule, d.team_id, d.assignee) == (Outcome.TEAM_QUEUE, Rule.AT_CAPACITY, 3, None)


def test_capacity_skips_full_agents():
    d = rules(max_open=5, candidates=[Candidate(1, "A", 5), Candidate(2, "B", 6), Candidate(3, "C", 4)])
    assert d.assignee_id == 3 and d.available == 1


def test_ties_never_assigned_first_then_least_recently_then_lowest_id():
    assert least_busy([Candidate(5, "x", 2, T0), Candidate(9, "y", 2, None)], 25).id == 9
    assert least_busy([Candidate(5, "x", 2, T0), Candidate(9, "y", 2, T0 - timedelta(hours=1))], 25).id == 9
    assert least_busy([Candidate(9, "y", 2, T0), Candidate(5, "x", 2, T0)], 25).id == 5
    assert least_busy([Candidate(9, "y", 2, None), Candidate(5, "x", 2, None)], 25).id == 5
    assert least_busy([Candidate(1, "x", 3, None), Candidate(2, "y", 1, T0)], 25).id == 2  # load beats recency
    assert least_busy([], 25) is None


# ------------------------------------------------------------------------------------------------ helpers
async def add_agents(org, team: str, *names: str, active: bool = True, role: str = "AGENT") -> list[User]:
    async with SessionLocal() as db:
        users = [
            User(
                name=n,
                email=f"{n.lower().replace(' ', '.')}@test.example",
                password_hash=_PASSWORD_HASH,
                role=role,
                team_id=org.teams[team].id,
                is_active=active,
            )
            for n in names
        ]
        db.add_all(users)
        await db.commit()
        return users


async def give_open_tickets(user_id: int, n: int, team_id: int) -> None:
    async with SessionLocal() as db:
        db.add_all(
            Ticket(subject="load", description="load", status="IN_PROGRESS", assignee_id=user_id, team_id=team_id)
            for _ in range(n)
        )
        await db.commit()


async def create(client, payload) -> dict:
    res = await client.post("/api/v1/tickets", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def routed(ticket: dict) -> dict:
    return next(e for e in reversed(ticket["timeline"]) if e["event_type"] == "routed")["metadata"]


async def audit_actions() -> list[str]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuditLog.action).order_by(AuditLog.id))).all())


# ------------------------------------------------------------------------------------------------ on creation
async def test_new_ticket_goes_to_the_least_busy_agent_of_the_category_team(client, org):
    team = org.teams["Payments Support"].id
    busy, quiet = await add_agents(org, "Payments Support", "Busy Bee", "Quiet Quinn")
    await give_open_tickets(org.agent.id, 3, team)
    await give_open_tickets(busy.id, 5, team)
    await give_open_tickets(quiet.id, 1, team)
    await add_agents(org, "Payments Support", "Idle Inactive", active=False)  # never chosen
    await add_agents(org, "Payments Support", "Team Admin", role="ADMIN")  # admins aren't routed tickets

    t = await create(client, PAYMENTS)
    assert t["status"] == "ASSIGNED" and t["assignee"]["name"] == "Quiet Quinn" and t["team"]["id"] == team
    meta = routed(t)
    assert meta["rule"] == "LEAST_BUSY" and meta["outcome"] == "assigned" and meta["trigger"] == "triage"
    assert meta["candidates"] == 3 and meta["open_tickets"] == 1
    work = [e for e in t["timeline"] if not e["event_type"].startswith("sla_")]
    assert [e["event_type"] for e in work][-2:] == ["routed", "status_changed"]
    assert work[-2]["actor"] is None  # the rules, not a person
    async with SessionLocal() as db:
        assert (await db.get(User, quiet.id)).last_assigned_at is not None


async def test_equal_loads_are_shared_round_robin(client, org):
    await add_agents(org, "Payments Support", "Second Agent", "Third Agent")
    names = [(await create(client, PAYMENTS))["assignee"]["name"] for _ in range(3)]
    assert sorted(names) == ["Arjun Agent", "Second Agent", "Third Agent"]


async def test_two_tickets_at_the_same_moment_get_different_agents(org):
    """The per-team advisory lock: without it both requests would see the same agent as least busy."""
    await add_agents(org, "Payments Support", "Second Agent")
    async with _client(auth_headers(org.admin)) as a, _client(auth_headers(org.admin)) as b:
        first, second = await asyncio.gather(
            a.post("/api/v1/tickets", json=PAYMENTS), b.post("/api/v1/tickets", json=PAYMENTS)
        )
    assert {first.json()["assignee"]["name"], second.json()["assignee"]["name"]} == {"Arjun Agent", "Second Agent"}


async def test_team_at_capacity_leaves_the_ticket_in_the_team_queue(client, org, monkeypatch):
    monkeypatch.setattr(get_settings(), "routing_max_open_per_agent", 1)
    assert (await create(client, PAYMENTS))["assignee"]["name"] == "Arjun Agent"
    t = await create(client, PAYMENTS)
    assert t["status"] == "TRIAGED" and t["assignee"] is None and t["team"]["name"] == "Payments Support"
    assert routed(t)["rule"] == "AT_CAPACITY"
    assert "auto_assign" in t["allowed_actions"]  # admin can re-run routing later


async def test_team_without_agents_queues_and_unowned_category_is_unrouted(client, org):
    t = await create(client, REFUND)
    assert t["status"] == "TRIAGED" and t["assignee"] is None and t["team"] is not None
    assert routed(t)["rule"] == "NO_AGENTS"
    async with SessionLocal() as db:
        from app.models import Category

        cat = await db.scalar(select(Category).where(Category.name == "Payments related"))
        cat.team_id = None
        await db.commit()
    t = await create(client, PAYMENTS)
    assert t["team"] is None and t["assignee"] is None and routed(t)["rule"] == "NO_TEAM"


# ------------------------------------------------------------------------------------------------ review queue
async def test_low_confidence_waits_for_review_then_confirmation_routes_it(client, agent_client, org, monkeypatch):
    monkeypatch.setattr(get_settings(), "review_threshold", 0.999)
    t = await create(client, PAYMENTS)
    assert t["needs_review"] and t["status"] == "TRIAGED" and t["team"] is None and t["assignee"] is None
    assert routed(t)["rule"] == "REVIEW" and routed(t)["outcome"] == "review"
    assert t["top_categories"][0][0] == "Payments related" and len(t["top_categories"]) >= 2
    assert "auto_assign" not in t["allowed_actions"]  # confirm the category first
    queue = (await client.get("/api/v1/tickets", params={"needs_review": "true", "status": "open"})).json()
    assert [i["id"] for i in queue["items"]] == [t["id"]] and queue["items"][0]["top_categories"]
    # Agents don't see unrouted tickets; the review queue is the Admin's.
    assert (await agent_client.get(f"/api/v1/tickets/{t['id']}")).status_code == 404
    res = await client.post(f"/api/v1/tickets/{t['id']}/auto-assign")
    assert res.status_code == 409 and "review queue" in res.json()["detail"]["message"]

    # Confirming the AI's category (same value) clears the flag and routes the ticket.
    res = await client.patch(f"/api/v1/tickets/{t['id']}", json={"category": "Payments related"})
    body = res.json()
    assert res.status_code == 200 and body["needs_review"] is False and body["labels_from"] == "human"
    assert body["status"] == "ASSIGNED" and body["assignee"]["name"] == "Arjun Agent"
    kinds = [e["event_type"] for e in body["timeline"]]
    assert kinds[-3:] == ["category_confirmed", "routed", "status_changed"]
    assert routed(body)["trigger"] == "category_confirmed"
    # A second confirmation is a no-op.
    again = (await client.patch(f"/api/v1/tickets/{t['id']}", json={"category": "Payments related"})).json()
    assert len(again["timeline"]) == len(body["timeline"])


async def test_correcting_the_category_moves_an_untouched_ticket_to_the_new_team(client, agent_client, org):
    t = await create(client, PAYMENTS)
    assert t["assignee"]["name"] == "Arjun Agent"
    # Arjun spots the wrong category before starting: it moves to Returns & Pickups (Olga).
    body = (await agent_client.patch(f"/api/v1/tickets/{t['id']}", json={"category": "Returns"})).json()
    assert body["status"] == "ASSIGNED" and body["assignee"]["name"] == "Olga Other"
    assert body["team"]["name"] == "Returns & Pickups" and routed(body)["trigger"] == "category_corrected"
    assert body["can_view"] is False  # the response to his own change, then it's out of his scope
    assert "ticket.reroute" in await audit_actions()
    # Arjun no longer sees it (not his, not his team's, not created by him).
    assert (await agent_client.get(f"/api/v1/tickets/{t['id']}")).status_code == 404


async def test_correction_to_a_team_without_agents_releases_the_ticket_to_that_queue(client, org):
    t = await create(client, PAYMENTS)
    body = (await client.patch(f"/api/v1/tickets/{t['id']}", json={"category": "Refund Related"})).json()
    assert body["status"] == "TRIAGED" and body["assignee"] is None and body["team"]["name"] != "Payments Support"
    moves = [
        (e["metadata"]["from"], e["metadata"]["to"]) for e in body["timeline"] if e["event_type"] == "status_changed"
    ]
    assert moves[-1] == ("ASSIGNED", "TRIAGED")


async def test_a_ticket_in_progress_keeps_its_owner_when_the_category_changes(client, agent_client, org):
    t = await create(client, PAYMENTS)
    await agent_client.patch(f"/api/v1/tickets/{t['id']}", json={"status": "IN_PROGRESS"})
    body = (await agent_client.patch(f"/api/v1/tickets/{t['id']}", json={"category": "Returns"})).json()
    assert body["assignee"]["name"] == "Arjun Agent" and body["team"]["name"] == "Payments Support"
    work = [e["event_type"] for e in body["timeline"] if not e["event_type"].startswith("sla_")]
    assert work[-1] == "category_corrected"  # no re-routing (the SLA re-targets to the new priority, see test_sla)


# ------------------------------------------------------------------------------------------------ auto-assign
async def test_admin_auto_assign_once_capacity_frees_up(client, agent_client, org, monkeypatch):
    monkeypatch.setattr(get_settings(), "routing_max_open_per_agent", 1)
    first = await create(client, PAYMENTS)
    waiting = await create(client, PAYMENTS)
    assert waiting["assignee"] is None
    res = await client.post(f"/api/v1/tickets/{waiting['id']}/auto-assign")
    assert res.status_code == 200 and res.json()["assignee"] is None  # still full: stays queued
    await agent_client.post(f"/api/v1/tickets/{first['id']}/resolve", json={"resolution": "Refunded"})
    assert (await agent_client.post(f"/api/v1/tickets/{waiting['id']}/auto-assign")).status_code == 403
    res = await client.post(f"/api/v1/tickets/{waiting['id']}/auto-assign")
    assert res.status_code == 200 and res.json()["assignee"]["name"] == "Arjun Agent"
    assert routed(res.json())["trigger"] == "manual"
    again = await client.post(f"/api/v1/tickets/{waiting['id']}/auto-assign")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "not_routable"


async def test_manual_assignment_counts_for_round_robin(client, org):
    (second,) = await add_agents(org, "Payments Support", "Second Agent")
    t = await create(client, RETURNS)  # Olga
    await client.post(f"/api/v1/tickets/{t['id']}/assign", json={"assignee_id": second.id})
    async with SessionLocal() as db:
        assert (await db.get(User, second.id)).last_assigned_at is not None
    # Equal load (1 each); Arjun was never assigned, so he is next.
    assert (await create(client, PAYMENTS))["assignee"]["name"] == "Arjun Agent"


@pytest.mark.parametrize("payload", [PAYMENTS, RETURNS])
async def test_every_creation_records_exactly_one_routing_decision(client, org, payload):
    t = await create(client, payload)
    assert [e["event_type"] for e in t["timeline"]].count("routed") == 1
