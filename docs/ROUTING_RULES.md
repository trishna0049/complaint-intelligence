# Routing rules

Routing decides which team and which agent get a new ticket. Like priority, it is decided by **deterministic
rules, never by the LLM** (spec: "Priority, SLA and routing use rules"). The rules live in
[`backend/app/domain/routing.py`](../backend/app/domain/routing.py) (pure, unit-tested); the service that applies them
is [`backend/app/services/routing.py`](../backend/app/services/routing.py).

```
category ──► owning team (Admin → Categories) ──► least-busy active agent of that team
```

## Rules, in order (the first that applies decides)

| Rule | Condition | Result |
|---|---|---|
| REVIEW | Category confidence below `REVIEW_THRESHOLD` (0.45) | Not routed. Waits in the Admin **Review queue** until a person confirms or corrects the category, then it is routed. |
| NO_TEAM | No team owns the category | Unrouted (no team, no agent) — an Admin assigns it. |
| NO_AGENTS | The owning team has no active agents | Team queue: team set, no agent. |
| AT_CAPACITY | Every agent of the team has `ROUTING_MAX_OPEN_PER_AGENT` (25) or more open tickets | Team queue. |
| LEAST_BUSY | Otherwise | The active agent with the fewest open tickets. Ties: never-assigned first, then the agent assigned least recently (`users.last_assigned_at`, also set by manual assignment), then the lowest user id — equal loads are shared round-robin. |

"Open" means NEW, TRIAGED, ASSIGNED, IN_PROGRESS, WAITING_CUSTOMER or ESCALATED. Admins and deactivated users never
receive routed tickets.

## When routing runs

- **On creation**, right after AI triage, in the same transaction as the ticket (NEW → TRIAGED → ASSIGNED).
- **After a category is confirmed or corrected**, but only while nobody has started on the ticket: TRIAGED and
  unassigned, or ASSIGNED to an agent outside the new category's team. A ticket that is IN_PROGRESS (or later)
  keeps its owner. If the new team has no free agent, an ASSIGNED ticket goes back to TRIAGED in that team's queue
  (system move `release`). The person who made the change gets the result even if the ticket left their scope.
- **Admin "Auto-assign"** (`POST /tickets/{id}/auto-assign`) on an unassigned TRIAGED ticket — for example once an
  agent of a full team has capacity again.

## Guarantees

- **No double assignment under load:** choosing an agent takes a per-team PostgreSQL advisory lock
  (`pg_advisory_xact_lock`) held until the transaction commits, so two tickets created at the same moment can't
  both see the same agent as least busy (covered by a concurrency test).
- **Explained:** every decision writes a `routed` timeline event with the rule, the reason, the team, the agent,
  their open load and how many agents were considered. Moving a ticket away from someone also writes
  `ticket.reroute` to the audit log.
