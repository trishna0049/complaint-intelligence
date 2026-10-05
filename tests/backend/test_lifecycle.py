"""Ticket lifecycle: the state machine, every action through the API, permissions, timeline + audit in the same
transaction, comments, attachments and customers."""

from __future__ import annotations

import itertools

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domain import lifecycle as lc
from app.domain.lifecycle import Action, InvalidTransition, Status, allowed_actions, next_status
from app.models import AuditLog, Ticket, TicketEvent, User

from .conftest import _PASSWORD_HASH, _client, auth_headers

PAYMENTS = {"description": "I was charged twice for my order of ₹12,500 and nobody helps", "channel": "Email"}
# Refund Related is owned by a team with no agents in the test org, so routing leaves it TRIAGED in that team's queue.
REFUND = {"description": "refund not received yet, where is my refund"}


# ------------------------------------------------------------------------------------------------ state machine (unit)
EXPECTED = {
    # action: (sources, target)
    Action.TRIAGE: ({"NEW"}, "TRIAGED"),
    Action.ASSIGN: ({"NEW", "TRIAGED", "ASSIGNED", "IN_PROGRESS", "WAITING_CUSTOMER", "ESCALATED"}, "ASSIGNED"),
    Action.RELEASE: ({"ASSIGNED"}, "TRIAGED"),
    Action.START: ({"ASSIGNED", "ESCALATED"}, "IN_PROGRESS"),
    Action.WAIT_CUSTOMER: ({"IN_PROGRESS"}, "WAITING_CUSTOMER"),
    Action.RESUME: ({"WAITING_CUSTOMER"}, "IN_PROGRESS"),
    Action.ESCALATE: ({"TRIAGED", "ASSIGNED", "IN_PROGRESS", "WAITING_CUSTOMER"}, "ESCALATED"),
    Action.RESOLVE: ({"ASSIGNED", "IN_PROGRESS", "WAITING_CUSTOMER", "ESCALATED"}, "RESOLVED"),
    Action.CLOSE: ({"RESOLVED"}, "CLOSED"),
    Action.REOPEN: ({"RESOLVED", "CLOSED"}, None),
}


def test_there_are_exactly_eight_states():
    assert [s.value for s in Status] == [
        "NEW",
        "TRIAGED",
        "ASSIGNED",
        "IN_PROGRESS",
        "WAITING_CUSTOMER",
        "ESCALATED",
        "RESOLVED",
        "CLOSED",
    ]


@pytest.mark.parametrize(("state", "action"), list(itertools.product(Status, Action)))
def test_every_state_action_pair(state, action):
    """All 80 combinations: legal ones land on the documented state, the rest raise InvalidTransition."""
    sources, target = EXPECTED[action]
    if state.value in sources:
        expected = target or "IN_PROGRESS"  # reopen with an assignee
        assert next_status(state, action, has_assignee=True) == expected
    else:
        with pytest.raises(InvalidTransition) as exc:
            next_status(state, action)
        assert state.value in str(exc.value)


def test_reopen_goes_back_to_the_owner_or_the_pool():
    assert next_status("CLOSED", "reopen", has_assignee=True) == Status.IN_PROGRESS
    assert next_status("RESOLVED", "reopen", has_assignee=False) == Status.TRIAGED


def test_allowed_actions_and_open_states():
    assert allowed_actions("IN_PROGRESS") == [Action.ASSIGN, Action.WAIT_CUSTOMER, Action.ESCALATE, Action.RESOLVE]
    assert allowed_actions("CLOSED") == [Action.REOPEN]
    assert Action.TRIAGE not in allowed_actions("NEW")  # system only
    assert Action.RELEASE not in allowed_actions("ASSIGNED")
    assert lc.is_open("ESCALATED") and not lc.is_open("RESOLVED")
    assert lc.SLA_PAUSED_STATUSES == {Status.WAITING_CUSTOMER}


def test_closed_is_terminal_except_for_reopen():
    for action in Action:
        if action is not Action.REOPEN:
            with pytest.raises(InvalidTransition):
                next_status("CLOSED", action)


# ------------------------------------------------------------------------------------------------ helpers
async def create(client, payload=PAYMENTS) -> dict:
    res = await client.post("/api/v1/tickets", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


async def events(ticket_id: int) -> list[tuple[str, dict | None]]:
    async with SessionLocal() as db:
        rows = (
            await db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.id))
        ).all()
        return [(e.event_type, e.metadata_) for e in rows]


async def audits() -> list[str]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuditLog.action).order_by(AuditLog.id))).all())


# ------------------------------------------------------------------------------------------------ happy path
async def test_full_lifecycle_through_the_api(client, org):
    # Created, triaged and routed in one go: Payments related -> Payments Support -> its only agent.
    t = await create(client)
    assert t["created_at"]
    assert [e["event_type"] for e in t["timeline"]] == ["created", "triaged", "routed", "status_changed"]
    assert t["timeline"][1]["metadata"]["category"] == "Payments related"
    assert (
        t["status"] == "ASSIGNED" and t["assignee"]["name"] == "Arjun Agent" and t["team"]["name"] == "Payments Support"
    )
    assert set(t["allowed_actions"]) == {"assign", "start", "escalate", "resolve"}
    tid = t["id"]
    t = (await client.patch(f"/api/v1/tickets/{tid}", json={"status": "IN_PROGRESS"})).json()
    assert t["status"] == "IN_PROGRESS"
    t = (await client.patch(f"/api/v1/tickets/{tid}", json={"status": "WAITING_CUSTOMER"})).json()
    assert t["status"] == "WAITING_CUSTOMER"
    t = (await client.patch(f"/api/v1/tickets/{tid}", json={"status": "IN_PROGRESS"})).json()  # resume
    t = (
        await client.post(f"/api/v1/tickets/{tid}/escalate", json={"reason": "Customer threatens legal action"})
    ).json()
    assert t["status"] == "ESCALATED" and t["escalated_at"]
    t = (await client.patch(f"/api/v1/tickets/{tid}", json={"status": "IN_PROGRESS"})).json()  # start again
    t = (
        await client.post(f"/api/v1/tickets/{tid}/resolve", json={"resolution": "Refunded the duplicate debit"})
    ).json()
    assert t["status"] == "RESOLVED" and t["resolved_at"] and t["resolution"] == "Refunded the duplicate debit"
    t = (await client.post(f"/api/v1/tickets/{tid}/close")).json()
    assert t["status"] == "CLOSED" and t["closed_at"] and t["allowed_actions"] == ["reopen"]
    t = (await client.post(f"/api/v1/tickets/{tid}/reopen", json={"reason": "Refund bounced"})).json()
    assert (
        t["status"] == "IN_PROGRESS" and t["reopen_count"] == 1 and t["resolved_at"] is None and t["closed_at"] is None
    )

    moves = [(m["from"], m["to"]) for kind, m in await events(tid) if kind == "status_changed"]
    assert moves == [
        ("TRIAGED", "ASSIGNED"),
        ("ASSIGNED", "IN_PROGRESS"),
        ("IN_PROGRESS", "WAITING_CUSTOMER"),
        ("WAITING_CUSTOMER", "IN_PROGRESS"),
        ("IN_PROGRESS", "ESCALATED"),
        ("ESCALATED", "IN_PROGRESS"),
        ("IN_PROGRESS", "RESOLVED"),
        ("RESOLVED", "CLOSED"),
        ("CLOSED", "IN_PROGRESS"),
    ]
    kinds = [k for k, _ in await events(tid)]
    assert {"created", "triaged", "routed", "escalated"} <= set(kinds)
    # Sensitive actions are audited; the admin closed a ticket assigned to someone else.
    assert {"ticket.escalate", "ticket.close_other", "ticket.reopen"} <= set(await audits())


async def test_invalid_moves_return_409_and_change_nothing(client, org):
    tid = (await create(client, REFUND))["id"]
    res = await client.post(f"/api/v1/tickets/{tid}/close")
    assert res.status_code == 409 and "TRIAGED" in res.json()["detail"]["message"]
    assert (await client.post(f"/api/v1/tickets/{tid}/resolve", json={"resolution": "done"})).status_code == 409
    assert (await client.patch(f"/api/v1/tickets/{tid}", json={"status": "WAITING_CUSTOMER"})).status_code == 409
    assert (await client.post(f"/api/v1/tickets/{tid}/reopen", json={"reason": "why not"})).status_code == 409
    detail = (await client.get(f"/api/v1/tickets/{tid}")).json()
    assert detail["status"] == "TRIAGED" and len(detail["timeline"]) == 3  # created, triaged, routed
    bad = await client.patch(f"/api/v1/tickets/{tid}", json={"status": "CLOSED"})
    assert bad.status_code == 422  # PATCH only does start / wait / resume
    assert (await client.post(f"/api/v1/tickets/{tid}/escalate", json={"reason": ""})).status_code == 422


async def test_event_and_audit_are_written_in_the_same_transaction(client, org, monkeypatch):
    """If the commit fails, neither the change nor its timeline/audit rows are kept."""
    tid = (await create(client))["id"]  # routed: ASSIGNED to Arjun
    from app.services import tickets as svc

    async def boom(db):  # the commit step of every action
        await db.flush()
        raise RuntimeError("database went away")

    monkeypatch.setattr(svc, "commit", boom)
    before_events, before_audits = len(await events(tid)), len(await audits())
    with pytest.raises(RuntimeError):
        await client.post(f"/api/v1/tickets/{tid}/escalate", json={"reason": "angry customer"})
    async with SessionLocal() as db:
        assert (await db.get(Ticket, tid)).status == "ASSIGNED"
    assert len(await events(tid)) == before_events and len(await audits()) == before_audits


# ------------------------------------------------------------------------------------------------ permissions
async def test_agents_see_only_own_team_and_created_tickets(client, agent_client, other_agent_client, org):
    payments = (await create(client))["id"]  # routed to Arjun (Payments Support)
    returns = (await create(client, {"description": "want to return damaged item please pick up"}))["id"]  # -> Olga
    refund = (await create(client, REFUND))["id"]  # Refunds team queue: nobody in the test org belongs to it
    mine = (await create(agent_client, {"description": "return pickup not done, created by Arjun"}))["id"]  # -> Olga

    def ids(page):
        return {i["id"] for i in page["items"]}

    assert ids((await client.get("/api/v1/tickets")).json()) == {payments, returns, refund, mine}
    assert ids((await agent_client.get("/api/v1/tickets")).json()) == {payments, mine}  # own + created
    assert ids((await other_agent_client.get("/api/v1/tickets")).json()) == {returns, mine}  # own team
    assert (await other_agent_client.get(f"/api/v1/tickets/{payments}")).status_code == 404  # not 403: no leak
    assert (
        await other_agent_client.post(f"/api/v1/tickets/{payments}/comments", json={"body": "hi"})
    ).status_code == 404
    number = (await client.get(f"/api/v1/tickets/{returns}")).json()["ticket_number"]
    res = await agent_client.get("/api/v1/tickets", params={"q": number})
    assert res.json()["total"] == 0
    summary = (await agent_client.get("/api/v1/tickets/summary")).json()
    assert summary["open"] == 2 and summary["by_status"]["ASSIGNED"] == 2  # both were routed on creation


async def test_agent_assignment_rules(client, agent_client, org):
    tid = (await create(client))["id"]
    # Routing gave it to Arjun (Payments Support)...
    async with SessionLocal() as db:
        teammate = User(
            name="Tara Teammate",
            email="tara@test.example",
            password_hash=_PASSWORD_HASH,
            role="AGENT",
            team_id=org.teams["Payments Support"].id,
        )
        db.add(teammate)
        await db.commit()
    assert (await client.get(f"/api/v1/tickets/{tid}")).json()["assignee"]["id"] == org.agent.id  # routed
    # ...reassign within the team...
    res = await agent_client.post(f"/api/v1/tickets/{tid}/assign", json={"assignee_id": teammate.id})
    assert res.status_code == 200 and res.json()["assignee"]["name"] == "Tara Teammate"
    # ...but not outside it (spec: Admin only).
    res = await agent_client.post(f"/api/v1/tickets/{tid}/assign", json={"assignee_id": org.other_agent.id})
    assert res.status_code == 403 and "outside your own team" in res.json()["detail"]["message"]
    res = await client.post(f"/api/v1/tickets/{tid}/assign", json={"assignee_id": org.other_agent.id})
    assert res.status_code == 200 and res.json()["team"]["name"] == "Returns & Pickups"
    assert (await audits()).count("ticket.reassign") == 2
    assert (await client.post(f"/api/v1/tickets/{tid}/assign", json={"assignee_id": 999})).status_code == 422
    same = await client.post(f"/api/v1/tickets/{tid}/assign", json={"assignee_id": org.other_agent.id})
    assert same.status_code == 409 and same.json()["detail"]["code"] == "no_change"


async def test_closing_someone_elses_ticket_is_admin_only(client, agent_client, org):
    tid = (await create(client))["id"]
    async with SessionLocal() as db:
        teammate = User(
            name="Tara Teammate",
            email="tara@test.example",
            password_hash=_PASSWORD_HASH,
            role="AGENT",
            team_id=org.teams["Payments Support"].id,
        )
        db.add(teammate)
        await db.commit()
    await client.post(f"/api/v1/tickets/{tid}/assign", json={"assignee_id": teammate.id})
    # A teammate's ticket: the agent may work on it (team ticket)...
    res = await agent_client.post(f"/api/v1/tickets/{tid}/resolve", json={"resolution": "Refund issued"})
    assert res.status_code == 200
    assert "close" not in res.json()["allowed_actions"]
    # ...but closing a ticket assigned to someone else needs the Admin role.
    res = await agent_client.post(f"/api/v1/tickets/{tid}/close")
    assert res.status_code == 403 and "Admin" in res.json()["detail"]["message"]
    async with _client(auth_headers(teammate)) as tara:
        assert (await tara.post(f"/api/v1/tickets/{tid}/close")).status_code == 200  # own ticket


async def test_creator_from_another_team_can_read_and_comment_but_not_change(client, agent_client, org):
    tid = (await create(agent_client, {"description": "want to return damaged item please pick up"}))["id"]
    assert (await client.get(f"/api/v1/tickets/{tid}")).json()["assignee"]["id"] == org.other_agent.id  # routed
    detail = (await agent_client.get(f"/api/v1/tickets/{tid}")).json()
    assert detail["allowed_actions"] == []
    assert (await agent_client.post(f"/api/v1/tickets/{tid}/comments", json={"body": "Any update?"})).status_code == 201
    assert (await agent_client.post(f"/api/v1/tickets/{tid}/escalate", json={"reason": "slow"})).status_code == 403


# -------------------------------------------------------------------------------- comments, files, customers
async def test_comments_set_first_response_and_appear_in_the_timeline(client, org):
    tid = (await create(client))["id"]
    res = await client.post(f"/api/v1/tickets/{tid}/comments", json={"body": "  Looking into it now.  "})
    assert res.status_code == 201
    c = res.json()
    assert c["body"] == "Looking into it now." and c["author"]["name"] == "Ada Admin" and c["ai_assisted"] is False
    detail = (await client.get(f"/api/v1/tickets/{tid}")).json()
    assert detail["first_response_at"] and len(detail["comments"]) == 1
    first = detail["first_response_at"]
    await client.post(f"/api/v1/tickets/{tid}/comments", json={"body": "Second note"})
    assert (await client.get(f"/api/v1/tickets/{tid}")).json()["first_response_at"] == first
    assert (await client.post(f"/api/v1/tickets/{tid}/comments", json={"body": "   "})).status_code == 422
    assert [e["event_type"] for e in (await client.get(f"/api/v1/tickets/{tid}/timeline")).json()][
        -1
    ] == "comment_added"


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def test_attachments_upload_download_and_validation(client, other_agent_client, org, tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "attachments_dir", tmp_path)
    tid = (await create(client))["id"]
    res = await client.post(
        f"/api/v1/tickets/{tid}/attachments", files={"file": ("../../etc/receipt.png", PNG, "image/png")}
    )
    assert res.status_code == 201, res.text
    att = res.json()
    assert (
        att["filename"] == "receipt.png" and att["size_bytes"] == len(PNG) and att["uploaded_by"]["name"] == "Ada Admin"
    )
    stored = list(tmp_path.iterdir())
    assert len(stored) == 1 and stored[0].name != "receipt.png"  # random storage key, not the user's name

    dl = await client.get(f"/api/v1/tickets/{tid}/attachments/{att['id']}")
    assert dl.status_code == 200 and dl.content == PNG
    assert "attachment" in dl.headers["content-disposition"] and dl.headers["x-content-type-options"] == "nosniff"
    assert (await other_agent_client.get(f"/api/v1/tickets/{tid}/attachments/{att['id']}")).status_code == 404

    spoofed = await client.post(
        f"/api/v1/tickets/{tid}/attachments",
        files={"file": ("invoice.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")},
    )
    assert spoofed.status_code == 422 and "doesn't match" in spoofed.json()["detail"]["message"]
    exe = await client.post(
        f"/api/v1/tickets/{tid}/attachments", files={"file": ("run.exe", b"MZ", "application/x-msdownload")}
    )
    assert exe.status_code == 415
    monkeypatch.setattr(get_settings(), "max_attachment_mb", 0)
    big = await client.post(f"/api/v1/tickets/{tid}/attachments", files={"file": ("a.txt", b"hello", "text/plain")})
    assert big.status_code == 413
    assert len(list(tmp_path.iterdir())) == 1  # rejected uploads leave nothing behind
    assert [e["event_type"] for e in (await client.get(f"/api/v1/tickets/{tid}")).json()["timeline"]][
        -1
    ] == "attachment_added"


async def test_customers_profile_and_previous_tickets(client, org):
    first = await create(client, {**PAYMENTS, "customer_name": "Ravi Kumar", "city": "Pune"})
    customer = first["customer"]
    assert (
        customer["customer_code"] == "CUS-00001" and customer["region"] == "West" and customer["segment"] == "Standard"
    )
    second = await create(client, {"description": "refund still not credited", "customer_code": "cus-00001"})
    assert second["customer"]["id"] == customer["id"] and second["customer_name"] == "Ravi Kumar"
    assert [p["id"] for p in second["previous_tickets"]] == [first["id"]]
    assert (await client.post("/api/v1/tickets", json={**PAYMENTS, "customer_code": "CUS-99999"})).status_code == 422


async def test_queue_filters(client, org):
    a = (await create(client))["id"]
    await create(client, {"description": "general question about something"})
    assert (await client.get(f"/api/v1/tickets/{a}")).json()["assignee"]["id"] == org.agent.id  # routed
    q = lambda **p: client.get("/api/v1/tickets", params=p)  # noqa: E731
    assert (await q(assignee="none")).json()["total"] == 1
    assert (await q(assignee=str(org.agent.id))).json()["items"][0]["id"] == a
    assert (await q(status="assigned,triaged")).json()["total"] == 2
    assert (await q(status="open")).json()["total"] == 2
    assert (await q(status="CLOSED")).json()["total"] == 0
    assert (await q(team_id=org.teams["Payments Support"].id)).json()["total"] == 1
    assert (await q(sort="updated")).status_code == 200


async def test_historical_tickets_show_their_real_timeline(client, org):
    async with SessionLocal() as db:
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        t = Ticket(
            subject="s",
            description="t",
            source="dataset",
            status="CLOSED",
            csat_score=4,
            created_at=now - timedelta(hours=3),
            first_response_at=now - timedelta(hours=2),
            resolved_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=2),
            assignee_id=org.agent.id,
        )
        db.add(t)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(TicketEvent)) == 0
    tl = (await client.get(f"/api/v1/tickets/{t.id}")).json()["timeline"]
    assert [e["event_type"] for e in tl] == ["created", "first_response", "status_changed"]
    assert tl[2]["metadata"]["historical"] is True and tl[2]["actor"]["name"] == "Arjun Agent"


async def test_team_members_with_open_load(client, agent_client, other_agent_client, org):
    tid = (await create(client))["id"]
    assert (await client.get(f"/api/v1/tickets/{tid}")).json()["assignee"]["id"] == org.agent.id  # routed
    team = org.teams["Payments Support"].id
    members = (await agent_client.get(f"/api/v1/teams/{team}/members")).json()
    assert members == [{"id": org.agent.id, "name": "Arjun Agent", "role": "AGENT", "open_tickets": 1}]
    assert (await other_agent_client.get(f"/api/v1/teams/{team}/members")).status_code == 403
    assert (await client.get(f"/api/v1/teams/{team}/members")).status_code == 200
    assert (await client.get("/api/v1/teams/999/members")).status_code == 404
