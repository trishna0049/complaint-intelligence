"""Seed the organisation: departments, one team per dataset category, the 12 categories, one admin and every agent
from the dataset's Agent_name column. Idempotent — existing rows (matched by name / e-mail) are left unchanged.

How agents are placed in teams: the dataset's org chart is 6 managers -> 40 supervisors -> 1,371 agents, and agents
are not specialised (almost every agent's most frequent category is Returns or Order Related). So whole supervisor
groups are allocated to the category teams in proportion to each category's ticket volume (largest remainder, at
least one group per team). Every agent of a supervisor joins that supervisor's team.

Usage:  python -m scripts.seed [--csv PATH] [--agents-per-team N]

`--agents-per-team N` seeds only the first N agents (alphabetically) of each team — used by the end-to-end tests
so setup stays fast (argon2 hashing of all 1,371 agents takes about a minute).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.auth.security import hash_password
from app.core.config import REPO_DIR, get_settings
from app.core.db import SessionLocal, dispose_engine
from app.models import Category, Department, Team, User
from scripts.seed_knowledge import seed_knowledge

EMAIL_DOMAIN = "shopzilla.example"

DEPARTMENTS = ["Finance Operations", "Order Fulfilment", "Customer Experience"]

# category -> (team, department, category description)
CATEGORY_TEAMS: dict[str, tuple[str, str, str]] = {
    "Payments related": ("Payments Support", "Finance Operations", "Failed, pending or duplicate payments, UPI, EMI"),
    "Refund Related": ("Refunds Desk", "Finance Operations", "Refund status, delays and amounts"),
    "Offers & Cashback": ("Offers & Cashback", "Finance Operations", "Coupons, cashback and offer eligibility"),
    "Order Related": ("Order Support", "Order Fulfilment", "Delivery delays, order status, installation and demo"),
    "Returns": ("Returns & Pickups", "Order Fulfilment", "Return requests, reverse pickup, wrong or damaged items"),
    "Cancellation": ("Cancellations", "Order Fulfilment", "Order cancellations and their refunds"),
    "Product Queries": ("Product Help", "Customer Experience", "Specifications, warranty and product information"),
    "Feedback": ("Customer Feedback", "Customer Experience", "Service feedback and agent behaviour"),
    "Shopzilla Related": ("Shopzilla Premium", "Customer Experience", "Membership, rewards and account services"),
    "App/website": ("App & Website Support", "Customer Experience", "Login, OTP and app or website errors"),
    "Onboarding related": ("Seller Onboarding", "Customer Experience", "Seller registration and onboarding"),
    "Others": ("General Support", "Customer Experience", "Anything that fits no other category"),
}


def email_for(name: str, taken: set[str]) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    local = re.sub(r"[^a-z0-9]+", ".", ascii_name.lower()).strip(".") or "agent"
    candidate, n = f"{local}@{EMAIL_DOMAIN}", 2
    while candidate in taken:
        candidate, n = f"{local}{n}@{EMAIL_DOMAIN}", n + 1
    taken.add(candidate)
    return candidate


def allocate_supervisors(supervisors: list[str], volume: dict[str, int]) -> dict[str, str]:
    """Largest-remainder allocation of supervisor groups to categories (each category gets at least one)."""
    cats = sorted(volume, key=lambda c: (-volume[c], c))
    if len(supervisors) < len(cats):
        raise ValueError("fewer supervisor groups than categories")
    spare = len(supervisors) - len(cats)
    total = sum(volume.values())
    quotas = {c: spare * volume[c] / total for c in cats}
    seats = {c: 1 + int(quotas[c]) for c in cats}
    for c in sorted(cats, key=lambda c: (-(quotas[c] - int(quotas[c])), c))[: len(supervisors) - sum(seats.values())]:
        seats[c] += 1
    order = [c for c in cats for _ in range(seats[c])]
    return dict(zip(sorted(supervisors), order, strict=True))


async def seed(csv_path: Path, agents_per_team: int | None = None) -> dict[str, object]:
    started = time.perf_counter()
    s = get_settings()
    async with SessionLocal() as db:
        # ---------------------------------------------------------------- departments + teams + categories
        depts = {d.name: d for d in (await db.scalars(select(Department))).all()}
        for name in DEPARTMENTS:
            if name not in depts:
                depts[name] = Department(name=name)
                db.add(depts[name])
        await db.flush()
        teams = {t.name: t for t in (await db.scalars(select(Team))).unique().all()}
        for _cat, (team, dept, _desc) in CATEGORY_TEAMS.items():
            if team not in teams:
                teams[team] = Team(name=team, department_id=depts[dept].id, description=f"Owns {_cat} tickets")
                db.add(teams[team])
        await db.flush()
        cats = {c.name: c for c in (await db.scalars(select(Category))).unique().all()}
        for cat, (team, _dept, desc) in CATEGORY_TEAMS.items():
            if cat not in cats:
                db.add(Category(name=cat, description=desc, team_id=teams[team].id))
        await db.flush()

        # ---------------------------------------------------------------- users
        existing = set((await db.scalars(select(User.email))).all())
        created_admin = False
        if s.seed_admin_email.lower() not in existing:
            db.add(
                User(
                    name="Platform Admin",
                    email=s.seed_admin_email.lower(),
                    password_hash=hash_password(s.seed_admin_password),
                    role="ADMIN",
                    is_active=True,
                    source="app",
                )
            )
            existing.add(s.seed_admin_email.lower())
            created_admin = True

        new_agents: list[dict[str, object]] = []
        if csv_path.is_file():
            df = pd.read_csv(csv_path, usecols=["Agent_name", "Supervisor", "category"])
            volume = df["category"].value_counts().to_dict()
            team_of_supervisor = allocate_supervisors(sorted(df["Supervisor"].dropna().unique()), volume)
            agents = df.dropna(subset=["Agent_name"]).groupby("Agent_name")["Supervisor"].first().sort_index()
            seeded_names = set((await db.scalars(select(User.name).where(User.source == "dataset"))).all())
            per_team: dict[str, int] = {}
            for name, supervisor in agents.items():
                team_name = CATEGORY_TEAMS[team_of_supervisor[supervisor]][0]
                per_team[team_name] = per_team.get(team_name, 0) + 1
                if name in seeded_names or (agents_per_team is not None and per_team[team_name] > agents_per_team):
                    continue
                new_agents.append(
                    {
                        "name": name,
                        "email": email_for(name, existing),
                        "supervisor": supervisor,
                        "team_id": teams[team_name].id,
                    }
                )
        else:
            print(f"note: {csv_path} not found - only the admin, teams and categories were seeded")

        if new_agents:
            # argon2 is deliberately slow (~50 ms); hash in parallel threads (the C library releases the GIL).
            with ThreadPoolExecutor(max_workers=16) as pool:
                hashes = list(pool.map(hash_password, [s.seed_agent_password] * len(new_agents)))
            for agent, pw_hash in zip(new_agents, hashes, strict=True):
                db.add(User(**agent, password_hash=pw_hash, role="AGENT", is_active=True, source="dataset"))
        await db.commit()

        summary_rows = (
            await db.execute(
                select(Team.name, User.email)
                .join(User, User.team_id == Team.id)
                .where(User.role == "AGENT")
                .order_by(Team.name, User.name)
            )
        ).all()
        kb = await seed_knowledge(db)
    await dispose_engine()
    first_agent: dict[str, str] = {}
    for team, email in summary_rows:
        first_agent.setdefault(team, email)
    print(
        f"seeded {len(DEPARTMENTS)} departments, {len(CATEGORY_TEAMS)} teams, {len(CATEGORY_TEAMS)} categories, "
        f"{'1 admin' if created_admin else 'admin already present'}, {len(new_agents):,} new agents "
        f"in {time.perf_counter() - started:.1f}s"
    )
    print(f"  knowledge base: {kb['created']} new articles, {kb['embedded']} embedded")
    print(f"  admin: {s.seed_admin_email} / {s.seed_admin_password}")
    if "Payments Support" in first_agent:
        print(f"  agent (Payments Support): {first_agent['Payments Support']} / {s.seed_agent_password}")
    return {"agents": len(new_agents), "first_agent": first_agent}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(REPO_DIR / "data" / "ecommerce_support.csv"))
    parser.add_argument("--agents-per-team", type=int, default=None, help="seed only N agents per team (e2e)")
    args = parser.parse_args()
    asyncio.run(seed(Path(args.csv), args.agents_per_team))


if __name__ == "__main__":
    main()
