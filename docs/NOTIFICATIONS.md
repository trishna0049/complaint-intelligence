# Notifications

Real-time in-app alerts plus optional e-mail (spec: "Notifications — real-time in-app alerts plus optional email").

## Who is told what

The notification worker ([backend/app/workers/notification.py](../backend/app/workers/notification.py)) turns events
into notifications:

| Event | Recipients | Severity | E-mail |
|---|---|---|---|
| `ticket.assigned` | the new assignee — "Routed to you by the rules" or "Assigned to you by …"; nobody is told about taking a ticket themselves | info | no |
| `ticket.escalated` | every active Admin except the one who escalated | warning (manual) / critical (SLA engine) | yes |
| `sla.warning` (80 %) | the assignee (unassigned ticket: the Admins) | warning | yes |
| `sla.breached` (100 %) | every active Admin and the assignee | critical | yes |

Notifications are rows in `notifications` (user, type, title, message, ticket, severity, read_at, created_at), written in
the worker's transaction together with its idempotency record, so a redelivered event never notifies twice.

## Real time

After the transaction commits, each notification is published on Redis pub/sub
(`pubsub:<database>:notifications:<user id>`), so it reaches the user's browser whichever API process their stream is
connected to. `GET /api/v1/notifications/stream` is a Server-Sent Events stream: `ready` (unread count), then
`notification` and `unread` events, with a comment heartbeat every `SSE_HEARTBEAT_SECONDS` (15 s). The browser reads
it with `fetch` streaming rather than `EventSource`, so the access token travels in the `Authorization` header — never
in a URL — and an expired token is renewed and the stream reopened (backoff up to 30 s).

In the app: the **bell** in the header (live unread count, latest notifications, mark all read), **toasts** for new
alerts (bottom right, severity shown by icon and label as well as colour), and the **Notifications** page (all /
unread, mark read, the e-mail preference).

## E-mail (optional)

Set `SMTP_HOST` (and `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `SMTP_FROM`) and escalations and SLA
alerts are also e-mailed, with a link to the ticket (`APP_BASE_URL`). Each user can switch e-mail off on the
Notifications page (`PUT /notifications/preferences`). Mail is sent after the commit; a failure is recorded on the
notification (`email_error`) and never loses the in-app alert. For local use, `.\scripts\dev.ps1 up` starts **Mailpit**:
SMTP on `localhost:11025`, inbox at http://localhost:18025.

## API

`GET /notifications?unread=&page=&page_size=` (own notifications + unread count) · `POST /notifications/{id}/read` ·
`POST /notifications/read-all` · `GET|PUT /notifications/preferences` · `GET /notifications/stream` (SSE). Everyone sees
only their own notifications (someone else's id answers 404).
