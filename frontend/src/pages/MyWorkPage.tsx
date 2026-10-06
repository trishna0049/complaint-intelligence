import { ArrowRight, BarChart3, Inbox, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useMyStats, useTicketSummary, useTickets } from "@/api/client";
import type { MyStats } from "@/api/types";
import type { Status } from "@/api/types";
import { useAuth } from "@/auth/useAuth";
import { SlaBadge } from "@/components/Sla";
import { TicketPriority, StatusBadge } from "@/components/Badges";
import { Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { fmtMinutes, fmtRelative, pct } from "@/lib/format";
import { statusLabel } from "@/lib/status";

const TILES: Status[] = ["ASSIGNED", "IN_PROGRESS", "WAITING_CUSTOMER", "ESCALATED", "RESOLVED"];

export function MyWorkPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const summary = useTicketSummary({ assignee: "me" });
  const atRisk = useTickets({ assignee: "me", sla: "at_risk", page_size: 1 });
  const breached = useTickets({ assignee: "me", sla: "breached", page_size: 1 });
  const mine = useTickets({ assignee: "me", status: "open", sort: "sla", page_size: 50 });
  const teamBacklog = useTickets(
    user?.team ? { assignee: "none", status: "open", team_id: user.team.id, page_size: 1 } : { assignee: "none", status: "open", page_size: 1 },
  );
  const stats = useMyStats();
  const firstName = user?.name.split(" ")[0] ?? "";

  return (
    <>
      <PageHeader
        title="My work"
        description={`Hi ${firstName} — your open tickets, the SLA due soonest first.`}
        actions={<Link to="/tickets/new"><Button variant="secondary" icon={<Plus className="h-4 w-4" />}>Create ticket</Button></Link>}
      />
      <div className="mb-5 grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-8">
        <Tile label="Open" value={summary.data?.open} loading={summary.isLoading} strong />
        <Tile label="SLA at risk" value={atRisk.data?.total} loading={atRisk.isLoading} warn={(atRisk.data?.total ?? 0) > 0} />
        <Tile label="SLA breached" value={breached.data?.total} loading={breached.isLoading} warn={(breached.data?.total ?? 0) > 0} />
        {TILES.map((s) => <Tile key={s} label={statusLabel(s)} value={summary.data?.by_status[s]} loading={summary.isLoading} />)}
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader title="Assigned to me" subtitle={mine.data ? `${mine.data.total} open` : undefined}
            actions={<Link to="/tickets?view=mine" className="text-xs text-brand-600 hover:underline">Open in queue</Link>} />
          {mine.error ? (
            <ErrorState error={mine.error} onRetry={() => void mine.refetch()} />
          ) : mine.isLoading || !mine.data ? (
            <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
          ) : mine.data.items.length === 0 ? (
            <EmptyState title="Nothing assigned to you" description="Pick up a ticket from your team's unassigned queue." icon={<Inbox className="h-6 w-6" />}
              action={<Link to="/tickets?view=unassigned"><Button size="sm" variant="secondary">View unassigned</Button></Link>} />
          ) : (
            <ul className="divide-y divide-slate-100">
              {mine.data.items.map((t) => (
                <li key={t.id}>
                  <button onClick={() => navigate(`/tickets/${t.id}`)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-slate-500">{t.ticket_number}</span>
                        <StatusBadge status={t.status} />
                        <SlaBadge sla={t.sla} compact />
                      </div>
                      <p className="mt-0.5 truncate text-sm font-medium text-slate-900">{t.subject}</p>
                      <p className="text-xs text-slate-500">{t.category ?? "Uncategorised"} · updated {fmtRelative(t.updated_at)}</p>
                    </div>
                    <TicketPriority priority={t.priority} status={t.status} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="h-fit space-y-5">
        <MyStatsCard stats={stats.data} loading={stats.isLoading} />
        <Card className="h-fit">
          <CardHeader title={user?.team ? `${user.team.name} backlog` : "Unassigned backlog"} />
          <div className="px-4 py-4">
            {teamBacklog.isLoading ? <Skeleton className="h-10" /> : (
              <>
                <p className="text-3xl font-semibold tracking-tight text-slate-900">{teamBacklog.data?.total.toLocaleString() ?? "—"}</p>
                <p className="text-sm text-slate-500">open tickets waiting for an owner</p>
                <Link to="/tickets?view=unassigned" className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:underline">
                  Pick one up <ArrowRight className="h-4 w-4" />
                </Link>
              </>
            )}
          </div>
        </Card>
        </div>
      </div>
    </>
  );
}

/** Spec: agent "My stats" — resolved this week (vs last), median resolution, SLA met, CSAT. */
function MyStatsCard({ stats, loading }: { stats: MyStats | undefined; loading: boolean }) {
  const delta = stats ? stats.resolved_this_week - stats.resolved_last_week : 0;
  return (
    <Card>
      <CardHeader title="My stats" subtitle="This week (since Monday)" icon={<BarChart3 className="h-4 w-4" />} />
      {loading || !stats ? <div className="p-4"><Skeleton className="h-24" /></div> : (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-4 text-sm" aria-label="My stats">
          <div>
            <dt className="text-xs text-slate-500">Resolved this week</dt>
            <dd className="text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">{stats.resolved_this_week.toLocaleString()}</dd>
            <dd className="text-xs text-slate-500">{stats.resolved_last_week.toLocaleString()} last week{delta !== 0 && ` (${delta > 0 ? "+" : ""}${delta})`}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">SLA met</dt>
            <dd className="text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">{pct(stats.sla_met_rate_this_week)}</dd>
            <dd className="text-xs text-slate-500">of tickets resolved this week</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Median resolution</dt>
            <dd className="font-semibold text-slate-900 tabular-nums">{fmtMinutes(stats.median_resolution_minutes_this_week)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">CSAT (30 days)</dt>
            <dd className="font-semibold text-slate-900 tabular-nums">{stats.avg_csat_30d?.toFixed(2) ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Waiting on customer</dt>
            <dd className="font-semibold text-slate-900 tabular-nums">{stats.waiting_on_customer.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Breached, still open</dt>
            <dd className={`font-semibold tabular-nums ${stats.sla_breached_open > 0 ? "text-rose-600" : "text-slate-900"}`}>{stats.sla_breached_open.toLocaleString()}</dd>
          </div>
        </dl>
      )}
    </Card>
  );
}

function Tile({ label, value, loading, strong, warn }: { label: string; value: number | undefined; loading: boolean; strong?: boolean; warn?: boolean }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      {loading ? <Skeleton className="mt-2 h-7 w-12" /> : (
        <p className={`mt-1 text-2xl font-semibold tracking-tight ${warn ? "text-rose-600" : strong ? "text-brand-700" : "text-slate-900"}`}>{(value ?? 0).toLocaleString()}</p>
      )}
    </Card>
  );
}
