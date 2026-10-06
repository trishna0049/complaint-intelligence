import { ArrowLeft, Loader2, Check, FileText, Route, ShieldQuestion, Sparkles, UserRound, Users } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "@/api/http";
import { useCategories, useTicket, useUpdateTicket } from "@/api/client";
import type { TicketDetail } from "@/api/types";
import { StatusBadge, TicketPriority } from "@/components/Badges";
import { ActionBar } from "@/components/ticket/ActionBar";
import { CopilotPanel } from "@/components/ticket/CopilotPanel";
import { Conversation } from "@/components/ticket/Conversation";
import { HelpArticles, SimilarTickets } from "@/components/ticket/Retrieval";
import { SlaBadge, SlaCard } from "@/components/Sla";
import { Timeline } from "@/components/ticket/Timeline";
import { TriageView } from "@/components/TriageView";
import { Avatar, Badge, Button, Card, CardHeader, EmptyState, ErrorState, LoadingState, Select, Skeleton } from "@/components/ui";
import { fmtDate, fmtDateTime, fmtInr, fmtRelative } from "@/lib/format";

export function TicketDetailPage() {
  const id = Number(useParams().id);
  const { data: t, isLoading, error, refetch } = useTicket(id);

  if (isLoading) return <LoadingState label="Loading ticket…" />;
  if (error) {
    return (
      <Card>
        {error instanceof ApiError && error.status === 404 ? (
          <EmptyState title="Ticket not found" description="It doesn't exist, or it belongs to a team you're not part of."
            action={<Link to="/tickets" className="text-sm text-brand-600 hover:underline">Back to the queue</Link>} />
        ) : (
          <ErrorState error={error} onRetry={() => void refetch()} />
        )}
      </Card>
    );
  }
  if (!t) return null;
  if (!t.can_view) return <MovedAway ticket={t} />;
  const done = t.status === "RESOLVED" || t.status === "CLOSED";
  const routing = [...t.timeline].reverse().find((e) => e.event_type === "routed");

  return (
    <div>
      <Link to="/tickets" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> Ticket queue
      </Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm text-slate-500">{t.ticket_number}</span>
            <StatusBadge status={t.status} />
            <TicketPriority priority={t.priority} status={t.status} />
            <SlaBadge sla={t.sla} />
            {t.needs_review && <Badge tone="violet"><Sparkles className="h-3 w-3" /> Needs review</Badge>}
            {t.reopen_count > 0 && <Badge tone="amber">Reopened ×{t.reopen_count}</Badge>}
          </div>
          <h1 className="mt-1.5 text-xl font-semibold tracking-tight text-slate-900">{t.subject}</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            {fmtRelative(t.created_at)} via {t.channel}{t.customer_name && ` · ${t.customer_name}`}{t.city && ` · ${t.city}`}
          </p>
        </div>
        <ActionBar ticket={t} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader title="Complaint" icon={<FileText className="h-4 w-4" />} subtitle={fmtDateTime(t.created_at)}
              actions={t.description_source === "template" ? <Badge tone="slate" title="The source dataset row had no remark text">Templated text</Badge> : undefined} />
            <p className="whitespace-pre-wrap px-4 py-3 text-sm leading-relaxed text-slate-800">{t.description}</p>
            {t.resolution && (
              <div className="mx-4 mb-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
                <span className="font-medium">Resolution: </span>{t.resolution}
              </div>
            )}
          </Card>

          <Card>
            <CardHeader
              title="AI triage"
              icon={<Sparkles className="h-4 w-4 text-violet-500" />}
              subtitle={t.labels_from === "dataset" ? "Historical record — category and intent are the dataset's own labels" :
                t.labels_from === "human" ? (lastCategoryEvent(t) === "category_confirmed" ? "AI category confirmed by a person" : "Category corrected by a person") :
                t.model_version ?? undefined}
            />
            <div className="p-4">
              {t.pipeline.triage === "failed" ? (
                <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">
                  Automatic triage failed after its retries and is waiting in the dead-letter queue. An Admin can replay
                  it from <b>Event pipeline</b>.
                </p>
              ) : t.pipeline.triage === "pending" ? (
                <div className="space-y-2" role="status">
                  <p className="flex items-center gap-2 text-sm text-slate-600">
                    <Loader2 className="h-4 w-4 animate-spin text-violet-500" /> The AI worker is triaging this ticket —
                    category, sentiment, entities, priority and routing appear in a moment.
                  </p>
                  <Skeleton className="h-12" />
                </div>
              ) : (
              <TriageView category={t.category} categoryConfidence={t.labels_from === "model" ? t.category_confidence : null}
                intent={t.intent} intentConfidence={t.labels_from === "model" ? t.intent_confidence : null}
                sentiment={t.sentiment} sentimentScore={t.sentiment_score} priority={t.priority} reasons={t.priority_reasons} entities={t.entities} />
              )}
              {!done && t.status !== "NEW" && t.allowed_actions.length > 0 && <CategoryCorrection ticket={t} />}
            </div>
          </Card>

          <CopilotPanel ticket={t} />
          <Conversation ticket={t} />
        </div>

        <aside className="space-y-5">
          <Card>
            <CardHeader title="Assignment" icon={<Users className="h-4 w-4" />} />
            <dl className="space-y-3 px-4 py-3 text-sm">
              <div>
                <dt className="text-xs text-slate-500">Assignee</dt>
                <dd className="mt-1 flex items-center gap-2 text-slate-800">
                  {t.assignee ? <><Avatar name={t.assignee.name} size="sm" />{t.assignee.name}</> : <span className="text-amber-700">Unassigned</span>}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Team</dt>
                <dd className="mt-0.5 text-slate-800">{t.team?.name ?? <span className="text-slate-400">Not routed</span>}</dd>
              </div>
              {routing?.metadata?.reason != null && (
                <div>
                  <dt className="text-xs text-slate-500">Routing</dt>
                  <dd className="mt-0.5 text-xs text-slate-600">{String(routing.metadata.reason)}</dd>
                </div>
              )}
              {t.escalated_at && (
                <div>
                  <dt className="text-xs text-slate-500">Escalated</dt>
                  <dd className="mt-0.5 text-rose-700">{fmtDateTime(t.escalated_at)}</dd>
                </div>
              )}
            </dl>
          </Card>

          <SlaCard sla={t.sla} />
          <CustomerCard ticket={t} />
          <HelpArticles ticketId={t.id} version={`${t.pipeline.triage}:${t.category ?? ""}`} />
          <SimilarTickets ticketId={t.id} version={`${t.pipeline.triage}:${t.category ?? ""}`} />

          <Card>
            <CardHeader title="Details" />
            <dl className="divide-y divide-slate-100 px-4 py-1 text-sm">
              {[
                ["Channel", t.channel],
                ["Order", t.order_id ?? "—"],
                ["Product", t.product ?? "—"],
                ["Amount", fmtInr(t.amount_inr)],
                ["City", t.city ?? "—"],
                ["CSAT", t.csat_score ? `${t.csat_score} / 5` : "—"],
                ["Source", t.source === "dataset" ? "Historical dataset" : "Created in app"],
                ["First response", fmtDateTime(t.first_response_at)],
                ["Resolved", fmtDateTime(t.resolved_at)],
                ["Closed", fmtDateTime(t.closed_at)],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 py-1.5">
                  <dt className="text-slate-500">{k}</dt>
                  <dd className="truncate text-right text-slate-800">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>

          <Timeline events={t.timeline} />
        </aside>
      </div>
    </div>
  );
}

function CustomerCard({ ticket }: { ticket: TicketDetail }) {
  const c = ticket.customer;
  return (
    <Card>
      <CardHeader title="Customer" icon={<UserRound className="h-4 w-4" />} subtitle={c ? c.customer_code : undefined} />
      {!c ? (
        <p className="px-4 py-3 text-sm text-slate-500">
          {ticket.source === "dataset" ? "Historical record — the dataset has no customer identifiers." : "No customer linked to this ticket."}
        </p>
      ) : (
        <div className="px-4 py-3 text-sm">
          <div className="flex items-center gap-2">
            <Avatar name={c.name} size="sm" />
            <div>
              <p className="font-medium text-slate-900">{c.name}</p>
              <p className="text-xs text-slate-500">{c.segment}{c.region ? ` · ${c.region} region` : ""} · customer since {fmtDate(c.created_at)}</p>
            </div>
          </div>
          <p className="mb-1.5 mt-3 text-xs font-medium text-slate-500">Previous tickets ({ticket.previous_tickets.length})</p>
          {ticket.previous_tickets.length === 0 ? (
            <p className="text-xs text-slate-400">This is the customer's first ticket.</p>
          ) : (
            <ul className="space-y-1.5">
              {ticket.previous_tickets.map((p) => (
                <li key={p.id}>
                  <Link to={`/tickets/${p.id}`} className="flex items-center justify-between gap-2 rounded px-1 py-0.5 hover:bg-slate-50">
                    <span className="min-w-0">
                      <span className="font-mono text-xs text-slate-500">{p.ticket_number}</span>
                      <span className="block truncate text-xs text-slate-700">{p.subject}</span>
                    </span>
                    <StatusBadge status={p.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

function lastCategoryEvent(t: TicketDetail): string | undefined {
  return [...t.timeline].reverse().find((e) => e.event_type === "category_confirmed" || e.event_type === "category_corrected")?.event_type;
}

function MovedAway({ ticket }: { ticket: TicketDetail }) {
  return (
    <Card>
      <EmptyState
        title={`${ticket.ticket_number} moved to ${ticket.team?.name ?? "another team"}`}
        description={`With the category ${ticket.category}, the routing rules gave it to ${ticket.assignee?.name ?? "that team's queue"}. It's no longer in your queue.`}
        icon={<Route className="h-6 w-6" />}
        action={<Link to="/my-work" className="text-sm text-brand-600 hover:underline">Back to My work</Link>}
      />
    </Card>
  );
}

function CategoryCorrection({ ticket }: { ticket: TicketDetail }) {
  const categories = useCategories();
  const update = useUpdateTicket(ticket.id);
  if (ticket.labels_from === "dataset") return null;
  const alternatives = ticket.top_categories.filter(([c]) => c !== ticket.category).slice(0, 2);
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 text-xs text-slate-500">
      {ticket.needs_review && ticket.category && (
        <div className="mb-1 flex w-full flex-wrap items-center gap-2 rounded-md bg-violet-50 px-3 py-2 text-violet-900">
          <ShieldQuestion className="h-4 w-4" />
          <span>Low confidence — not routed until a person confirms the category.</span>
          <Button size="sm" icon={<Check className="h-3.5 w-3.5" />} disabled={update.isPending} onClick={() => update.mutate({ category: ticket.category! })}>
            Confirm {ticket.category}
          </Button>
          {alternatives.map(([c, p]) => (
            <Button key={c} size="sm" variant="secondary" disabled={update.isPending} onClick={() => update.mutate({ category: c })}>
              {c} <span className="text-slate-400">{Math.round(p * 100)}%</span>
            </Button>
          ))}
        </div>
      )}
      <span>Wrong category? Correct it (priority is recalculated by the rules):</span>
      <Select aria-label="Correct category" className="h-8 w-48 text-xs" value={ticket.category ?? ""}
        onChange={(e) => update.mutate({ category: e.target.value })} disabled={update.isPending}>
        {categories.data?.map((c) => <option key={c.name}>{c.name}</option>)}
      </Select>
      {update.isError && <span className="text-rose-600">{update.error.message}</span>}
    </div>
  );
}
