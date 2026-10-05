import { ArrowRight, Check, ClipboardCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useCategories, useTickets, useUpdateTicket } from "@/api/client";
import type { Ticket, TicketDetail } from "@/api/types";
import { ConfidenceMeter, PriorityBadge, SentimentBadge } from "@/components/Badges";
import { Button, Card, EmptyState, ErrorState, PageHeader, Select, Skeleton } from "@/components/ui";
import { fmtRelative } from "@/lib/format";

/**
 * Low-confidence review queue (Admin): tickets whose category the classifier wasn't sure about are not routed.
 * Confirming the AI's category or picking another one routes the ticket by the rules (team -> least-busy agent).
 */
export function ReviewQueuePage() {
  const [page, setPage] = useState(1);
  const queue = useTickets({ needs_review: "true", status: "open", sort: "oldest", page, page_size: 20 });
  const [reviewed, setReviewed] = useState<TicketDetail[]>([]);

  return (
    <>
      <PageHeader
        title="Review queue"
        description="The classifier wasn't confident about these categories, so they weren't routed. Confirm or correct each one — it is then routed to the owning team's least-busy agent."
      />
      {reviewed.length > 0 && (
        <Card className="mb-4">
          <p className="border-b border-slate-100 px-4 py-2.5 text-xs font-medium text-slate-500">Just reviewed</p>
          <ul className="divide-y divide-slate-100" aria-label="Just reviewed">
            {reviewed.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm" role="status">
                <Check className="h-4 w-4 text-emerald-600" />
                <Link to={`/tickets/${r.id}`} className="font-mono text-xs text-brand-700 hover:underline">{r.ticket_number}</Link>
                <span className="font-medium text-slate-900">{r.category}</span>
                <ArrowRight className="h-3.5 w-3.5 text-slate-400" />
                <span className="text-slate-700">{r.team?.name ?? "Unrouted"}{r.assignee ? ` · ${r.assignee.name}` : " · team queue"}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card>
        {queue.error ? (
          <ErrorState error={queue.error} onRetry={() => void queue.refetch()} />
        ) : queue.isLoading || !queue.data ? (
          <div className="space-y-3 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
        ) : queue.data.items.length === 0 ? (
          <EmptyState title="Nothing to review" description="Every open ticket has a confident or confirmed category." icon={<ClipboardCheck className="h-6 w-6" />} />
        ) : (
          <>
            <p className="border-b border-slate-100 px-4 py-2.5 text-xs text-slate-500">{queue.data.total.toLocaleString()} waiting · oldest first</p>
            <ul className="divide-y divide-slate-100" aria-label="Tickets to review">
              {queue.data.items.map((t) => <ReviewRow key={t.id} ticket={t} onReviewed={(r) => setReviewed((prev) => [r, ...prev].slice(0, 10))} />)}
            </ul>
            {queue.data.total > queue.data.page_size && (
              <div className="flex justify-end gap-2 border-t border-slate-100 px-4 py-2.5">
                <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
                <Button size="sm" variant="ghost" disabled={page * queue.data.page_size >= queue.data.total} onClick={() => setPage(page + 1)}>Next</Button>
              </div>
            )}
          </>
        )}
      </Card>
    </>
  );
}

function ReviewRow({ ticket: t, onReviewed }: { ticket: Ticket; onReviewed: (result: TicketDetail) => void }) {
  const update = useUpdateTicket(t.id);
  const categories = useCategories();
  const [other, setOther] = useState("");
  const alternatives = t.top_categories.filter(([c]) => c !== t.category).slice(0, 2);

  const choose = (category: string) => update.mutate({ category }, { onSuccess: onReviewed });

  return (
    <li className="px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <Link to={`/tickets/${t.id}`} className="font-mono text-brand-700 hover:underline">{t.ticket_number}</Link>
            <PriorityBadge priority={t.priority} />
            <SentimentBadge sentiment={t.sentiment} />
            <span>{t.channel} · {fmtRelative(t.created_at)}</span>
          </div>
          <p className="mt-1 truncate text-sm font-medium text-slate-900">{t.subject}</p>
          <p className="mt-1 flex items-center gap-2 text-xs text-slate-600">
            AI suggests <span className="font-medium text-slate-900">{t.category ?? "—"}</span>
            <ConfidenceMeter value={t.category_confidence} />
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {t.category && (
            <Button size="sm" icon={<Check className="h-3.5 w-3.5" />} loading={update.isPending && update.variables?.category === t.category}
              disabled={update.isPending} onClick={() => choose(t.category!)}>
              Confirm {t.category}
            </Button>
          )}
          {alternatives.map(([c, p]) => (
            <Button key={c} size="sm" variant="secondary" disabled={update.isPending} onClick={() => choose(c)}>
              {c} <span className="text-slate-400">{Math.round(p * 100)}%</span>
            </Button>
          ))}
          <Select aria-label={`Other category for ${t.ticket_number}`} className="h-8 w-44 text-xs" value={other} disabled={update.isPending}
            onChange={(e) => { setOther(e.target.value); if (e.target.value) choose(e.target.value); }}>
            <option value="">Other category…</option>
            {categories.data?.map((c) => <option key={c.name}>{c.name}</option>)}
          </Select>
        </div>
      </div>
      {update.isError && <p className="mt-2 text-xs text-rose-700" role="alert">{update.error.message}</p>}
    </li>
  );
}
