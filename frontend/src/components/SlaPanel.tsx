import { AlarmClock, Timer } from "lucide-react";
import { Link } from "react-router-dom";
import { useSlaAnalytics } from "@/api/client";
import type { SlaBreakdown } from "@/api/types";
import { Card, CardHeader, ErrorState, Skeleton } from "@/components/ui";
import { fmtDuration, pct } from "@/lib/format";

/** Admin dashboard: SLA breach rate (spec: "SLA breach rate"), what is at risk right now, and where breaches happen. */
export function SlaPanel({ days }: { days: number }) {
  const { data, isLoading, error, refetch } = useSlaAnalytics(days);
  return (
    <Card>
      <CardHeader title="SLA" icon={<Timer className="h-4 w-4" />} subtitle={`Tickets created in the last ${days} days with an SLA clock`}
        actions={<Link to="/tickets?view=sla_risk" className="text-xs text-brand-600 hover:underline">At-risk queue</Link>} />
      {error ? <ErrorState error={error} onRetry={() => void refetch()} /> : isLoading || !data ? (
        <div className="grid gap-3 p-4 md:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
      ) : (
        <div className="space-y-4 p-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Breach rate" value={data.breach_rate === null ? "—" : pct(data.breach_rate, 1)}
              sub={`${data.breached.toLocaleString()} of ${data.with_sla.toLocaleString()} tickets`} />
            <Stat label="At risk now" value={data.open.at_risk.toLocaleString()} sub="open, 80 %+ of the target used" warn={data.open.at_risk > 0}
              link="/tickets?view=sla_risk" />
            <Stat label="Breached, still open" value={data.open.breached.toLocaleString()} sub="escalated automatically" warn={data.open.breached > 0}
              link="/tickets?view=sla_breached" />
            <Stat label="Avg. resolution" value={data.avg_resolution_minutes === null ? "—" : fmtDuration(data.avg_resolution_minutes * 60)}
              sub={data.avg_target_minutes === null ? "" : `vs ${fmtDuration(data.avg_target_minutes * 60)} target on average`} />
          </div>
          <div className="grid gap-5 md:grid-cols-2">
            <BreachBars title="Breach rate by priority" rows={data.by_priority} />
            <BreachBars title="Breach rate by team (top 6)" rows={data.by_team.slice(0, 6)} />
          </div>
        </div>
      )}
    </Card>
  );
}

function Stat({ label, value, sub, warn, link }: { label: string; value: string; sub?: string; warn?: boolean; link?: string }) {
  const body = (
    <>
      <p className="flex items-center gap-1 text-xs font-medium text-slate-500">
        {warn && <AlarmClock className="h-3.5 w-3.5 text-rose-600" aria-label="needs attention" />}{label}
      </p>
      <p className="mt-0.5 text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">{value}</p>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </>
  );
  return link ? <Link to={link} className="rounded-md border border-slate-200 px-3 py-2 hover:bg-slate-50">{body}</Link>
    : <div className="rounded-md border border-slate-200 px-3 py-2">{body}</div>;
}

/** One series (breach rate) as a ranked bar list: thin bars, value as text beside each, hover shows the counts. */
function BreachBars({ title, rows }: { title: string; rows: SlaBreakdown[] }) {
  const max = Math.max(0.01, ...rows.map((r) => r.breach_rate ?? 0));
  return (
    <figure>
      <figcaption className="mb-2 text-xs font-semibold text-slate-600">{title}</figcaption>
      {rows.length === 0 ? <p className="text-xs text-slate-400">No tickets with an SLA in this period.</p> : (
        <table className="w-full text-xs" aria-label={title}>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="group" title={`${r.name}: ${r.breached.toLocaleString()} breached of ${r.with_sla.toLocaleString()}`}>
                <th scope="row" className="w-32 truncate py-1 pr-2 text-left font-normal text-slate-700">{r.name}</th>
                <td className="py-1">
                  <div className="h-2.5 rounded-r bg-brand-500 transition-opacity group-hover:opacity-80"
                    style={{ width: `${Math.max(1, ((r.breach_rate ?? 0) / max) * 100)}%` }} />
                </td>
                <td className="w-24 py-1 pl-2 text-right tabular-nums text-slate-700">
                  {r.breach_rate === null ? "—" : pct(r.breach_rate, 1)} <span className="text-slate-400">({r.with_sla.toLocaleString()})</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </figure>
  );
}
