import { BookOpen, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { useSimilarTickets, useTicketArticles } from "@/api/client";
import type { MatchedBy } from "@/api/types";
import { StatusBadge } from "@/components/Badges";
import { Badge, Card, CardHeader, ErrorState, Skeleton } from "@/components/ui";

const MATCH: Record<MatchedBy, string> = { meaning: "Meaning", keywords: "Keywords", both: "Meaning + keywords" };

export function MatchBadge({ matchedBy, similarity }: { matchedBy: MatchedBy; similarity: number | null }) {
  return (
    <span className="text-[11px] tabular-nums text-slate-400" title={`Matched by ${MATCH[matchedBy].toLowerCase()}`}>
      {similarity !== null ? `${Math.round(similarity * 100)}% match` : "keyword match"}
    </span>
  );
}

function Loading() {
  return <div className="space-y-2 p-4"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>;
}

/** Past tickets like this one (hybrid search, limited to what the user may see). */
export function SimilarTickets({ ticketId, version }: { ticketId: number; version?: string }) {
  const { data, isLoading, error, refetch } = useSimilarTickets(ticketId, version);
  return (
    <Card>
      <CardHeader title="Similar tickets" icon={<Search className="h-4 w-4" />} subtitle="By meaning and keywords" />
      {error ? <ErrorState error={error} onRetry={() => void refetch()} /> : isLoading || !data ? <Loading /> : data.length === 0 ? (
        <p className="px-4 py-4 text-sm text-slate-500">No similar tickets found.</p>
      ) : (
        <ul className="divide-y divide-slate-100" aria-label="Similar tickets">
          {data.map((s) => (
            <li key={s.id}>
              <Link to={`/tickets/${s.id}`} className="block px-4 py-2.5 hover:bg-slate-50">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-slate-500">{s.ticket_number}</span>
                  <MatchBadge matchedBy={s.matched_by} similarity={s.similarity} />
                </div>
                <p className="mt-0.5 line-clamp-2 text-xs text-slate-700">{s.snippet}</p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <StatusBadge status={s.status} />
                  {s.category && <span className="text-[11px] text-slate-500">{s.category}</span>}
                  {s.csat_score && <span className="text-[11px] text-slate-500">· CSAT {s.csat_score}/5</span>}
                </div>
                {s.resolution && <p className="mt-1 line-clamp-2 text-[11px] text-emerald-700">Resolved: {s.resolution}</p>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Knowledge-base articles relevant to this ticket. */
export function HelpArticles({ ticketId, version }: { ticketId: number; version?: string }) {
  const { data, isLoading, error, refetch } = useTicketArticles(ticketId, version);
  return (
    <Card>
      <CardHeader title="Help articles" icon={<BookOpen className="h-4 w-4" />}
        actions={<Link to="/knowledge" className="text-xs text-brand-600 hover:underline">Knowledge base</Link>} />
      {error ? <ErrorState error={error} onRetry={() => void refetch()} /> : isLoading || !data ? <Loading /> : data.length === 0 ? (
        <p className="px-4 py-4 text-sm text-slate-500">No relevant articles.</p>
      ) : (
        <ul className="divide-y divide-slate-100" aria-label="Help articles">
          {data.map((a) => (
            <li key={a.id}>
              <Link to={`/knowledge/${a.id}`} className="block px-4 py-2.5 hover:bg-slate-50">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-slate-900">{a.title}</span>
                  <MatchBadge matchedBy={a.matched_by} similarity={a.similarity} />
                </div>
                <p className="mt-0.5 line-clamp-2 text-xs text-slate-600">{a.snippet}</p>
                {a.category && <Badge tone="slate" className="mt-1">{a.category}</Badge>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
