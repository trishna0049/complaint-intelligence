# Events — Kafka, outbox, workers, retries and the dead-letter queue

Ticket creation is instant: the API saves the ticket (status NEW) and its `ticket.created` event in **one database
transaction** and returns. Kafka fans the events out to four background workers that do the AI work, so a slow model or
an LLM outage never slows down or breaks the API.

```
API change ─(same transaction)─► outbox row ─► relay ─► Kafka topic <prefix>.<event> ─► worker (consumer group)
                                                                                      ├ processed_events: once only
                                                                                      └ 3 retries ─► dead_letters + <prefix>.dlq
```

## Event catalogue (spec: "Kafka events")

| Event | Produced when | Consumed by |
|---|---|---|
| `ticket.created` | a ticket is submitted | **AI worker** — triage, routing, embedding |
| `ai.analysis.completed` | triage finished | **LLM worker** (drafts the copilot answer), **SLA worker** (starts the clock) |
| `ticket.assigned` | routed or reassigned | **Notification worker** |
| `ticket.updated` / `ticket.resolved` | status or category changes / resolved | **AI worker** (embeddings + analytics), **SLA worker** (pause / stop) |
| `ticket.escalated` | manual or automatic escalation | **Notification worker** (alerts admins) |
| `sla.warning` | 80 % of the SLA used | **Notification worker** (alerts the agent) |
| `sla.breached` | 100 % of the SLA used | **SLA worker** (auto-escalation), **Notification worker** (alerts admins) |

Every message is an envelope: `event_id` (UUID), `type`, `timestamp`, `ticket_id`, `actor` (`{id, name, role}`, id null
= the system), `payload` (a snapshot of the ticket — number, status, priority, category, assignee, team — plus the
change's details) and `replay_of` (set on an Admin replay). One topic per event type, 3 partitions, **keyed by ticket
id** so a ticket's events are processed in order. Domain events are derived from the ticket timeline in one place
([backend/app/services/timeline.py](../backend/app/services/timeline.py)), so every change on the timeline that matters
to another part of the system is published, and nothing else.

The SLA worker also runs the scanner that emits `sla.warning` / `sla.breached` and escalates on a breach ([SLA.md](SLA.md)); the notification worker turns assignments, escalations and SLA alerts into live notifications and e-mail ([NOTIFICATIONS.md](NOTIFICATIONS.md)).

## Guarantees

- **Nothing lost, nothing phantom (outbox pattern).** The event row commits or rolls back with the change. The relay
  ([backend/app/events/kafka.py](../backend/app/events/kafka.py)) takes unpublished rows with `FOR UPDATE SKIP LOCKED`
  (several relays can run), sends them (`acks=all`, idempotent producer) and marks them published only after Kafka
  acknowledged them. If Kafka is down the rows stay, with the attempt count and the last error, and are sent when it is
  back (backoff up to 30 s).
- **Exactly-once effect (idempotent consumers).** Kafka delivers at least once. Each consumer records
  `(consumer, event_id)` in `processed_events` **in the same transaction as its own writes**; a redelivered event is
  skipped. Offsets are committed only after an event was processed, skipped or dead-lettered.
- **Retries and the dead-letter queue.** A failing handler is retried 3 times with exponential backoff
  (`EVENT_RETRIES`, `EVENT_RETRY_BACKOFF_SECONDS`). Then the event is stored in `dead_letters` and copied to the
  `<prefix>.dlq` topic, and the consumer moves on — one bad event never blocks a partition.
- **Replay.** An Admin replays a dead letter from **Admin → Event pipeline** (`POST /admin/dlq/{id}/replay`): the
  original event is published again with the **same event id**, so the consumers that already handled it skip it and
  only the one that failed runs again. Discard (`POST /admin/dlq/{id}/discard`) closes it. Both are audited.

## Running it

```powershell
.\scripts\dev.ps1 up        # Postgres, Redis, Kafka (KRaft, localhost:19092) and Kafka UI (http://localhost:18090)
.\scripts\dev.ps1 topics    # create the topics for EVENTS_PREFIX (idempotent; `topics --reset` recreates them)
.\scripts\dev.ps1 workers   # relay + AI, LLM, SLA and notification workers in one process
.\scripts\dev.ps1 workers ai   # ...or one of them (run several copies: Kafka shares the partitions)
.\scripts\dev.ps1 start     # topics, then API + workers + web app in three windows
```

`python -m app.workers.run all --health-port 18190` serves `GET /health` (200 while the relay and every worker run).
**Admin → Event pipeline** shows the outbox lag, what each worker processed (last hour / total), and the DLQ.

Settings (`.env`): `KAFKA_BOOTSTRAP_SERVERS`, `EVENTS_MODE` (`kafka` | `inline`), `EVENTS_PREFIX` (topic and
consumer-group prefix — the e2e run uses `e2e` on the same broker), `EVENT_RETRIES`, `COPILOT_AUTO` (the LLM worker drafts
the copilot answer after triage; set `false` to avoid API cost).

**Inline mode** (`EVENTS_MODE=inline`) runs the same consumers inside the API process right after each commit — same
idempotency, retries and DLQ, only synchronous. The unit tests use it; `tests/backend/test_kafka_integration.py`
covers the real broker (flow, duplicate delivery, retries → DLQ topic → replay, relay during a Kafka outage), and the
Playwright run uses Kafka and the workers end to end.
