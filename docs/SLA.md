# SLA engine

Every triaged ticket gets a resolution deadline from an **SLA policy**, a live countdown, a warning at 80 % and an
automatic escalation at 100 %. Deadlines, pauses and escalations are rules — never the LLM.

## Policies (Admin → SLA policies, `/sla-policies`)

| Default policy | Priority | Target |
|---|---|---|
| Critical — 2 hours | Critical | 120 min (the spec's example) |
| High — 8 hours | High | 480 min |
| Medium — 24 hours | Medium | 1,440 min |
| Low — 3 days | Low | 4,320 min |

An Admin can add a **category-specific** policy for a priority (e.g. *Payments related · Critical — 1 hour*); the most
specific active policy wins. A priority's default can't be deleted or switched off (every ticket needs a target). A
changed target applies to clocks started afterwards; running clocks keep the target they started with. All changes are
audited.

## The clock ([backend/app/domain/sla.py](../backend/app/domain/sla.py), unit-tested)

- **Start** — when triage completes (SLA worker on `ai.analysis.completed`). The clock counts from the ticket's
  creation: the customer has been waiting since then.
- **Pause rule** — while the ticket is `WAITING_CUSTOMER` the clock stops and the deadline moves out by exactly the
  time spent waiting. Every pause adds up. A paused clock is never warned or breached.
- **Re-target** — a category correction that changes the priority (or category policy) keeps the start and the pauses
  and changes only the target.
- **Stop** — `RESOLVED` stops the clock: **met** if the time used ≤ target, otherwise **breached**. A reopen resumes
  the clock without counting the time the ticket spent resolved. A breach is never undone.
- **Warning and breach** — the SLA worker's scanner (every `SLA_SCAN_SECONDS`, default 5 s) fires `sla.warning` at
  80 % and `sla.breached` at 100 % of the target, **once each** per ticket (row lock + recorded timestamps, so several
  scanners are safe). On `sla.breached` the SLA worker **escalates the ticket automatically** (reason *SLA breached
  (policy)*, audited); the notification worker alerts the agent (warning) and the admins (breach) in step 10.

Each change is logged in `sla_events` (started, paused, resumed, retargeted, warning, breached, stopped) with the
deadline at that moment, and on the ticket timeline.

## In the app

- A live **SLA badge** on the ticket and in the queue: green *On track · 1h 12m left*, amber *At risk* from 80 %, red
  *Breached · 14m over*, grey *Paused* while waiting on the customer, *SLA met* after a timely resolution. The badge
  crosses thresholds live in the browser; the page refreshes while the SLA worker catches up with a change.
- An **SLA card** on the ticket (policy, % of the target used, due, started, paused, warned, breached).
- Queue views **SLA at risk** / **SLA breached** and the sort **SLA due soonest**; **My work** shows the agent's at-risk
  and breached counts and lists their tickets by deadline.
- The Admin dashboard's **SLA** panel and `GET /analytics/sla`: breach rate (overall, by priority, category, team and
  over time), average resolution vs target, open tickets at risk / breached / paused.

## History

Migration 0009 gives the 85,907 imported tickets their real outcome: each ran from the reported time to the response
that closed it, against the default policy of its priority — Critical 28 % breached, High 11 %, Medium 3 %, Low 0.4 %
(median time to response 5 minutes, mean 170 minutes, because a minority of contacts waited days).

## Demo speed-up

`SLA_SPEEDUP=120` (in `.env`, for the workers) makes every target run 120× faster — the Critical 2-hour SLA lapses in
one minute, so the warning, the breach and the automatic escalation can be watched live. Leave it at `1` for real use.
