import { AlarmClock, Clock, Repeat, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { usePerformance, useWorkload } from "@/api/client";
import type { CategoryBreakdowns, Granularity, Performance, SegmentRates, TimingBy } from "@/api/types";
import { Card, CardHeader, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { fmtDate, fmtMinutes, fmtMonth, pct } from "@/lib/format";

// Same recessive chart chrome and single series hue as the rest of the dashboard.
const GRID = "#e1e0d9";
const AXIS = "#898781";
const SERIES_1 = "#2a78d6";
const axisProps = { stroke: AXIS, fontSize: 11, tickLine: false, axisLine: { stroke: "#c3c2b7" } };
const tooltipStyle = { fontSize: 12, borderRadius: 8, border: "1px solid rgba(11,11,11,0.10)", boxShadow: "0 4px 12px rgba(0,0,0,0.08)" };

type Measure = "first_response" | "resolution";
const MEASURES: { value: Measure; label: string }[] = [
  { value: "first_response", label: "First response" },
  { value: "resolution", label: "Resolution" },
];

/** Spec: "average response time", "average resolution time" (+ medians and p90, over time) and "repeat complaint rate". */
export function PerformancePanel({ days, granularity }: { days: number; granularity: Granularity }) {
  const { data, error, isLoading, refetch } = usePerformance(days, granularity);
  const [measure, setMeasure] = useState<Measure>("first_response");
  const fmtBucket = (d: string) => (granularity === "month" ? fmtMonth(d) : fmtDate(d).slice(0, 6));
  const key = measure === "first_response" ? "median_first_response_minutes" : "median_resolution_minutes";

  return (
    <Card>
      <CardHeader title="Response & resolution times" icon={<Clock className="h-4 w-4" />}
        subtitle={`Tickets created in the last ${days} days — time from creation to the first agent reply and to resolution`} />
      {error ? <ErrorState error={error} onRetry={() => void refetch()} /> : isLoading || !data ? (
        <div className="grid gap-3 p-4 md:grid-cols-5">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
      ) : data.tickets === 0 ? <EmptyState title="No tickets in this period" /> : (
        <div className="space-y-4 p-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Avg. first response" value={fmtMinutes(data.first_response.avg_minutes)}
              sub={`median ${fmtMinutes(data.first_response.median_minutes)} · p90 ${fmtMinutes(data.first_response.p90_minutes)}`} />
            <Stat label="Avg. resolution" value={fmtMinutes(data.resolution.avg_minutes)}
              sub={`median ${fmtMinutes(data.resolution.median_minutes)} · p90 ${fmtMinutes(data.resolution.p90_minutes)}`} />
            <Stat label="Responded" value={pct(data.first_response.coverage)} sub={`${data.first_response.count.toLocaleString()} of ${data.tickets.toLocaleString()} tickets`} />
            <Stat label="Resolved" value={pct(data.resolution.coverage)} sub={`${data.resolution.count.toLocaleString()} of ${data.tickets.toLocaleString()} tickets`} />
            <RepeatStat data={data} />
          </div>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <figure>
              <div className="mb-2 flex items-center justify-between gap-2">
                <figcaption className="text-xs font-semibold text-slate-600">Median {measure === "first_response" ? "first response" : "resolution"} time per {granularity}</figcaption>
                <div className="flex rounded-md border border-slate-200 bg-white p-0.5" role="group" aria-label="Measure">
                  {MEASURES.map((m) => (
                    <button key={m.value} onClick={() => setMeasure(m.value)} aria-pressed={measure === m.value}
                      className={`rounded px-2 py-0.5 text-xs font-medium ${measure === m.value ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>
              {data.trend.length === 0 ? <EmptyState title="No data" /> : (
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={data.trend} margin={{ top: 8, right: 16, bottom: 0, left: -4 }}>
                    <CartesianGrid stroke={GRID} vertical={false} />
                    <XAxis dataKey="date" {...axisProps} tickFormatter={fmtBucket} minTickGap={24} />
                    <YAxis {...axisProps} tickFormatter={(v: number) => fmtMinutes(v)} width={56} />
                    <Tooltip contentStyle={tooltipStyle} labelFormatter={(d) => fmtBucket(String(d))}
                      formatter={(v, _n, item) => [`${fmtMinutes(Number(v))} median · ${(item as { payload: { tickets: number } }).payload.tickets.toLocaleString()} tickets`, ""]}
                      separator="" />
                    <Line type="monotone" dataKey={key} name="Median" stroke={SERIES_1} strokeWidth={2} dot={granularity !== "day"} activeDot={{ r: 4 }} connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </figure>
            <div className="space-y-4">
              <TimingTable title="By channel" rows={data.by_channel} />
              <TimingTable title="By priority" rows={data.by_priority} />
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

function RepeatStat({ data }: { data: Performance }) {
  const r = data.repeat;
  return (
    <Stat label="Repeat complaints" value={pct(r.repeat_rate, 1)} icon={<Repeat className="h-3.5 w-3.5 text-slate-400" />}
      sub={`${r.repeats.toLocaleString()} repeats: ${r.repeat_cue.toLocaleString()} say so, ${r.returning_customer.toLocaleString()} returning within ${r.window_days}d`} />
  );
}

function TimingTable({ title, rows }: { title: string; rows: TimingBy[] }) {
  return (
    <table className="table-base" aria-label={`Times ${title.toLowerCase()}`}>
      <thead><tr><th>{title}</th><th className="text-right">Tickets</th><th className="text-right">Median 1st resp.</th><th className="text-right">Median resolution</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <td>{r.name}</td>
            <td className="text-right tabular-nums text-slate-500">{r.tickets.toLocaleString()}</td>
            <td className="text-right tabular-nums">{fmtMinutes(r.median_first_response_minutes)}</td>
            <td className="text-right tabular-nums">{fmtMinutes(r.median_resolution_minutes)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------------------------------------- segment rates
type Segment = "channel_rates" | "city_rates" | "product_rates";
const SEGMENTS: { value: Segment; label: string; field: string }[] = [
  { value: "channel_rates", label: "Channel", field: "channel" },
  { value: "city_rates", label: "City", field: "city" },
  { value: "product_rates", label: "Product", field: "product" },
];

/** Spec: rates by channel / city / product. City and product are recorded on a fraction of tickets: show the coverage. */
export function SegmentRatesPanel({ data, days }: { data: CategoryBreakdowns; days: number }) {
  const [segment, setSegment] = useState<Segment>("channel_rates");
  const info = SEGMENTS.find((s) => s.value === segment)!;
  const rates: SegmentRates = data[segment];
  const max = Math.max(1, ...rates.items.map((r) => r.count));
  return (
    <Card>
      <CardHeader title={`Rates by ${info.label.toLowerCase()}`} subtitle={`Last ${days} days`}
        actions={
          <div className="flex rounded-md border border-slate-200 bg-white p-0.5" role="group" aria-label="Segment">
            {SEGMENTS.map((s) => (
              <button key={s.value} onClick={() => setSegment(s.value)} aria-pressed={segment === s.value}
                className={`rounded px-2 py-0.5 text-xs font-medium ${segment === s.value ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                {s.label}
              </button>
            ))}
          </div>
        } />
      <p className="px-4 pt-3 text-xs text-slate-500" data-testid="coverage">
        Data coverage: {info.field} is recorded on <span className="font-medium text-slate-700">{pct(rates.coverage)}</span> of tickets
        ({rates.with_value.toLocaleString()}){rates.coverage !== null && rates.coverage < 0.5 ? " — read the rates as indicative only." : "."}
      </p>
      {rates.items.length === 0 ? <EmptyState title={`No ${info.field} recorded in this period`} /> : (
        <div className="overflow-x-auto p-1">
          <table className="table-base" aria-label={`Rates by ${info.field}`}>
            <thead>
              <tr><th>{info.label}</th><th className="w-1/4">Tickets</th><th className="text-right">Negative</th><th className="text-right">High / critical</th>
                <th className="text-right">SLA breach</th><th className="text-right">CSAT</th></tr>
            </thead>
            <tbody>
              {rates.items.map((r) => (
                <tr key={r.name}>
                  <td className="max-w-[160px] truncate">{r.name}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      <div className="h-2 rounded-r bg-brand-500" style={{ width: `${Math.max(2, (r.count / max) * 100)}%` }} aria-hidden />
                      <span className="tabular-nums text-slate-600">{r.count.toLocaleString()}</span>
                    </div>
                  </td>
                  <td className="text-right tabular-nums">{pct(r.negative_share)}</td>
                  <td className="text-right tabular-nums">{pct(r.high_priority_share)}</td>
                  <td className="text-right tabular-nums">{pct(r.breach_rate, 1)}</td>
                  <td className="text-right tabular-nums">{r.avg_csat?.toFixed(2) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------------------------- workload
/** Spec: team workload and agent workload. Live (not windowed): what is open right now plus the last 7 days' flow. */
export function WorkloadPanel() {
  const { data, error, isLoading, refetch } = useWorkload();
  return (
    <Card>
      <CardHeader title="Workload" icon={<Users className="h-4 w-4" />} subtitle="Open tickets right now, and the last 7 days' intake and resolutions"
        actions={<Link to="/tickets?view=unassigned" className="text-xs text-brand-600 hover:underline">Unassigned queue</Link>} />
      {error ? <ErrorState error={error} onRetry={() => void refetch()} /> : isLoading || !data ? (
        <div className="p-4"><Skeleton className="h-48" /></div>
      ) : (
        <div className="grid gap-5 p-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div className="overflow-x-auto">
            <table className="table-base" aria-label="Team workload">
              <thead>
                <tr><th>Team</th><th className="text-right">Agents</th><th className="w-1/5">Open</th><th className="text-right">Unassigned</th>
                  <th className="text-right">Per agent</th><th className="text-right">SLA at risk</th><th className="text-right">Breached</th>
                  <th className="text-right">In / out 7d</th></tr>
              </thead>
              <tbody>
                {data.teams.map((t) => {
                  const max = Math.max(1, ...data.teams.map((x) => x.open));
                  return (
                    <tr key={t.team_id}>
                      <td className="max-w-[160px] truncate">{t.team}</td>
                      <td className="text-right tabular-nums">{t.agents}</td>
                      <td>
                        <div className="flex items-center gap-2">
                          <div className="h-2 rounded-r bg-brand-500" style={{ width: `${Math.max(2, (t.open / max) * 100)}%` }} aria-hidden />
                          <span className="tabular-nums text-slate-600">{t.open.toLocaleString()}</span>
                        </div>
                      </td>
                      <td className="text-right tabular-nums">{t.unassigned.toLocaleString()}</td>
                      <td className="text-right tabular-nums">{t.open_per_agent === null ? <span className="text-slate-400" title="No active agents">no agents</span> : t.open_per_agent.toFixed(1)}</td>
                      <td className="text-right tabular-nums"><Flag n={t.at_risk} /></td>
                      <td className="text-right tabular-nums"><Flag n={t.breached_open} /></td>
                      <td className="text-right tabular-nums text-slate-500">{t.created_7d.toLocaleString()} / {t.resolved_7d.toLocaleString()}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="font-medium">
                  <td>All teams</td><td className="text-right tabular-nums">{data.totals.agents}</td><td className="tabular-nums">{data.totals.open.toLocaleString()}</td>
                  <td className="text-right tabular-nums">{data.totals.unassigned.toLocaleString()}</td><td /><td className="text-right tabular-nums">{data.totals.at_risk.toLocaleString()}</td><td /><td />
                </tr>
              </tfoot>
            </table>
          </div>
          <div className="overflow-x-auto">
            {data.agents.length === 0 ? <EmptyState title="No agent has open or recently resolved tickets" /> : (
              <table className="table-base" aria-label="Agent workload">
                <thead><tr><th>Agent</th><th className="text-right">Open</th><th className="text-right">At risk</th><th className="text-right">Resolved 7d</th><th className="text-right">Median res.</th></tr></thead>
                <tbody>
                  {data.agents.map((a) => (
                    <tr key={a.user_id}>
                      <td className="max-w-[180px]"><span className="block truncate">{a.name}</span><span className="block truncate text-xs text-slate-500">{a.team ?? "No team"}</span></td>
                      <td className="text-right tabular-nums">{a.open.toLocaleString()}</td>
                      <td className="text-right tabular-nums"><Flag n={a.at_risk + a.breached_open} title={`${a.at_risk} at risk, ${a.breached_open} breached`} /></td>
                      <td className="text-right tabular-nums">{a.resolved_7d.toLocaleString()}</td>
                      <td className="text-right tabular-nums">{fmtMinutes(a.median_resolution_minutes_7d)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

/** A count that needs attention: status colour reserved for it, always with an icon (never colour alone). */
function Flag({ n, title }: { n: number; title?: string }) {
  if (n === 0) return <span className="text-slate-400">0</span>;
  return (
    <span className="inline-flex items-center gap-1 font-medium text-rose-600" title={title}>
      <AlarmClock className="h-3.5 w-3.5" aria-label="needs attention" />{n.toLocaleString()}
    </span>
  );
}

function Stat({ label, value, sub, icon }: { label: string; value: string; sub?: string; icon?: ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 px-3 py-2">
      <p className="flex items-center gap-1 text-xs font-medium text-slate-500">{icon}{label}</p>
      <p className="mt-0.5 text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">{value}</p>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </div>
  );
}
