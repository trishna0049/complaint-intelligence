import { AlertTriangle, ArrowDownRight, ArrowUpRight, Lightbulb, TrendingUp } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useCategoryBreakdowns, useEmerging, useOverview, useTrends } from "@/api/client";
import type { Breakdown, EmergingIssue, Granularity } from "@/api/types";
import { PriorityBadge, SentimentBadge } from "@/components/Badges";
import { SENTIMENT_COLORS, SENTIMENTS } from "@/lib/colors";
import { Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { fmtDate, fmtMonth, pct } from "@/lib/format";

// Chart chrome (recessive): hairline grid, muted axis ink.
const GRID = "#e1e0d9";
const AXIS = "#898781";
const SERIES_1 = "#2a78d6"; // blue — total volume / single-series bars
const SERIES_2 = "#eb6834"; // orange — high-priority volume
const RANGES = [7, 30, 90];
const GRANULARITIES: Granularity[] = ["day", "week", "month"];

const axisProps = { stroke: AXIS, fontSize: 11, tickLine: false, axisLine: { stroke: "#c3c2b7" } };
const tooltipStyle = { fontSize: 12, borderRadius: 8, border: "1px solid rgba(11,11,11,0.10)", boxShadow: "0 4px 12px rgba(0,0,0,0.08)" };

export function DashboardPage() {
  const [days, setDays] = useState<number>(30);
  const [granularity, setGranularity] = useState<Granularity>("day");
  const overview = useOverview(days);
  const trends = useTrends(days, granularity);
  const breakdowns = useCategoryBreakdowns(days);
  const emerging = useEmerging();
  const data = overview.data;
  const refetchAll = () => {
    void overview.refetch();
    void trends.refetch();
    void breakdowns.refetch();
    void emerging.refetch();
  };
  const firstError = overview.error ?? trends.error ?? breakdowns.error ?? emerging.error;
  const fmtBucket = (d: string) => (granularity === "month" ? fmtMonth(d) : fmtDate(d).slice(0, 6));

  return (
    <>
      <PageHeader
        title="Complaint dashboard"
        description="Volumes, sentiment and high-priority issues across all tickets."
        actions={<Segmented label="Time range" options={RANGES.map((r) => ({ value: r, label: `${r}d` }))} value={days} onChange={setDays} />}
      />
      {firstError ? (
        <Card><ErrorState error={firstError} onRetry={refetchAll} /></Card>
      ) : overview.isLoading || !data ? (
        <DashboardSkeleton />
      ) : data.kpis.total === 0 ? (
        <Card>
          <EmptyState
            title="No tickets in this period"
            description="Import the dataset (scripts\dev.ps1 import) or create a ticket."
            action={<Link to="/tickets/new" className="text-sm font-medium text-brand-600 hover:underline">Create ticket</Link>}
          />
        </Card>
      ) : (
        <div className={`space-y-5 transition-opacity ${overview.isFetching ? "opacity-70" : ""}`}>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <Kpi label="Tickets" value={data.kpis.total.toLocaleString()} change={data.kpis.total_change_pct} sub={`last ${days} days`} />
            <Kpi label="High / critical" value={data.kpis.high_priority.toLocaleString()} change={data.kpis.high_priority_change_pct} invert
              sub={`${data.kpis.critical.toLocaleString()} critical`} />
            <Kpi label="Negative sentiment" value={pct(data.kpis.negative_share)} sub="of scored tickets" />
            <Kpi label="Average CSAT" value={data.kpis.avg_csat?.toFixed(2) ?? "—"} sub="out of 5" />
            <Kpi label="Open high-priority" value={data.kpis.open_high_priority.toLocaleString()} sub={`${data.kpis.needs_review} need AI review`} alert={data.kpis.open_high_priority > 0} />
          </div>

          <Card className="border-brand-100 bg-gradient-to-r from-brand-50/70 to-white">
            <div className="flex gap-3 px-4 py-3">
              <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
              <ul className="space-y-1 text-sm text-slate-800">
                {data.insights.map((s) => <li key={s}>{s}</li>)}
              </ul>
            </div>
          </Card>

          <div className="grid gap-5 xl:grid-cols-2">
            <ChartCard title="Ticket volume" subtitle={`Per ${granularity} — all tickets vs high/critical priority`}
              actions={<Segmented label="Granularity" options={GRANULARITIES.map((g) => ({ value: g, label: g[0].toUpperCase() + g.slice(1) }))} value={granularity} onChange={setGranularity} small />}>
              {!trends.data ? <Skeleton className="h-[260px]" /> : (
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={trends.data.points} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
                    <CartesianGrid stroke={GRID} vertical={false} />
                    <XAxis dataKey="date" {...axisProps} tickFormatter={fmtBucket} minTickGap={24} />
                    <YAxis {...axisProps} allowDecimals={false} />
                    <Tooltip contentStyle={tooltipStyle} labelFormatter={(d) => fmtBucket(String(d))} />
                    <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
                    <Line type="monotone" dataKey="total" name="All tickets" stroke={SERIES_1} strokeWidth={2} dot={granularity !== "day"} activeDot={{ r: 4 }} />
                    <Line type="monotone" dataKey="high_priority" name="High / critical" stroke={SERIES_2} strokeWidth={2} dot={granularity !== "day"} activeDot={{ r: 4 }} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </ChartCard>

            <ChartCard title="Sentiment trend" subtitle={`Per ${granularity}, tickets with a sentiment score (Hugging Face model)`}>
              {!trends.data ? <Skeleton className="h-[260px]" /> : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={trends.data.points} margin={{ top: 8, right: 16, bottom: 0, left: -8 }} barCategoryGap={2}>
                    <CartesianGrid stroke={GRID} vertical={false} />
                    <XAxis dataKey="date" {...axisProps} tickFormatter={fmtBucket} minTickGap={24} />
                    <YAxis {...axisProps} allowDecimals={false} />
                    <Tooltip contentStyle={tooltipStyle} labelFormatter={(d) => fmtBucket(String(d))} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {SENTIMENTS.map((s, i) => (
                      <Bar key={s} dataKey={s} stackId="s" fill={SENTIMENT_COLORS[s]} stroke="#fcfcfb" strokeWidth={1}
                        radius={i === SENTIMENTS.length - 1 ? [3, 3, 0, 0] : 0} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              )}
            </ChartCard>
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <ChartCard title="Tickets by category" subtitle="Hover for negative-sentiment share" className="xl:col-span-2">
              {!breakdowns.data ? <Skeleton className="h-[260px]" /> : (
                <HorizontalBars rows={breakdowns.data.categories} height={Math.max(220, breakdowns.data.categories.length * 26)} />
              )}
            </ChartCard>
            <ChartCard title="Sentiment mix" subtitle={`Last ${days} days`}>
              {!breakdowns.data ? <Skeleton className="h-[200px]" /> : <SentimentMix rows={breakdowns.data.sentiment} />}
            </ChartCard>
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <ChartCard title="Top intents" subtitle="Sub-category of the complaint">
              {!breakdowns.data ? <Skeleton className="h-[300px]" /> : <HorizontalBars rows={breakdowns.data.intents} height={300} compact />}
            </ChartCard>
            <Card>
              <CardHeader title="Emerging issues" subtitle="Last 7 days vs the 7 days before" icon={<TrendingUp className="h-4 w-4" />} />
              {!emerging.data ? <div className="p-4"><Skeleton className="h-40" /></div> : <EmergingTable rows={emerging.data.emerging} />}
            </Card>
            <Card>
              <CardHeader title="Open high-priority tickets" icon={<AlertTriangle className="h-4 w-4 text-rose-500" />}
                actions={<Link to="/tickets?sort=priority" className="text-xs text-brand-600 hover:underline">View all</Link>} />
              {data.high_priority_open.length === 0 ? (
                <EmptyState title="Nothing urgent" description="No open high or critical tickets." />
              ) : (
                <ul className="divide-y divide-slate-100">
                  {data.high_priority_open.map((c) => (
                    <li key={c.id}>
                      <Link to={`/tickets/${c.id}`} className="block px-4 py-2.5 hover:bg-slate-50">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-sm font-medium text-slate-900">{c.subject}</span>
                          <PriorityBadge priority={c.priority} />
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                          <span className="font-mono">{c.ticket_number}</span>
                          <span>{c.category ?? "Uncategorised"}</span>
                          <SentimentBadge sentiment={c.sentiment} />
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          {breakdowns.data && (
            <div className="grid gap-5 md:grid-cols-2">
              <ChartCard title="By channel"><SimpleTable rows={breakdowns.data.channels} /></ChartCard>
              <ChartCard title="By priority"><SimpleTable rows={breakdowns.data.priorities} /></ChartCard>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function Segmented<T extends string | number>({ label, options, value, onChange, small }: {
  label: string; options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; small?: boolean;
}) {
  return (
    <div className="flex rounded-md border border-slate-200 bg-white p-0.5 shadow-sm" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          onClick={() => onChange(o.value)}
          className={`rounded font-medium ${small ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm"} ${value === o.value ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"}`}
          aria-pressed={value === o.value}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Kpi({ label, value, sub, change, invert, alert }: { label: string; value: string; sub?: string; change?: number | null; invert?: boolean; alert?: boolean }) {
  const up = (change ?? 0) >= 0;
  const good = invert ? !up : up;
  return (
    <Card className="px-4 py-3">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tracking-tight ${alert ? "text-rose-600" : "text-slate-900"}`}>{value}</p>
      <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
        {change !== undefined && change !== null && (
          <span className={`inline-flex items-center font-medium ${good ? "text-emerald-700" : "text-rose-600"}`}>
            {up ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
            {Math.abs(change).toFixed(0)}%
          </span>
        )}
        {sub}
      </div>
    </Card>
  );
}

function ChartCard({ title, subtitle, children, className, actions }: { title: string; subtitle?: string; children: ReactNode; className?: string; actions?: ReactNode }) {
  return (
    <Card className={className}>
      <CardHeader title={title} subtitle={subtitle} actions={actions} />
      <div className="p-3">{children}</div>
    </Card>
  );
}

function HorizontalBars({ rows, height, compact }: { rows: Breakdown[]; height: number; compact?: boolean }) {
  if (rows.length === 0) return <EmptyState title="No data" />;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 24, bottom: 0, left: 8 }} barCategoryGap={4}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" {...axisProps} allowDecimals={false} />
        <YAxis type="category" dataKey="name" {...axisProps} width={compact ? 170 : 130} interval={0} />
        <Tooltip
          contentStyle={tooltipStyle}
          cursor={{ fill: "rgba(0,0,0,0.04)" }}
          formatter={(v, _n, item) => {
            const r = (item as { payload: Breakdown }).payload;
            return [`${Number(v).toLocaleString()} tickets · ${pct(r.negative_share)} negative · ${r.high_priority.toLocaleString()} high/critical`, ""];
          }}
          separator=""
        />
        <Bar dataKey="count" fill={SERIES_1} radius={[0, 4, 4, 0]} maxBarSize={18} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function SentimentMix({ rows }: { rows: { name: string; count: number }[] }) {
  const total = rows.reduce((a, r) => a + r.count, 0);
  if (total === 0) return <EmptyState title="No sentiment scores yet" />;
  return (
    <div className="space-y-3 px-1 py-2">
      <div className="flex h-4 overflow-hidden rounded-full" role="img" aria-label="Sentiment distribution">
        {rows.map((r) => r.count > 0 && (
          <div key={r.name} style={{ width: `${(r.count / total) * 100}%`, background: SENTIMENT_COLORS[r.name] }} className="border-r-2 border-white last:border-r-0" title={`${r.name}: ${r.count}`} />
        ))}
      </div>
      <table className="w-full text-sm">
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <td className="py-1"><span className="mr-2 inline-block h-2.5 w-2.5 rounded-sm align-middle" style={{ background: SENTIMENT_COLORS[r.name] }} />{r.name}</td>
              <td className="py-1 text-right tabular-nums text-slate-600">{r.count.toLocaleString()}</td>
              <td className="w-16 py-1 text-right tabular-nums text-slate-500">{pct(r.count / total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EmergingTable({ rows }: { rows: EmergingIssue[] }) {
  if (rows.length === 0) return <EmptyState title="Not enough data" description="Needs at least two weeks of complaints." />;
  return (
    <table className="table-base">
      <thead>
        <tr><th>Category</th><th className="text-right">This wk</th><th className="text-right">Last wk</th><th className="text-right">Change</th></tr>
      </thead>
      <tbody>
        {rows.slice(0, 8).map((r) => (
          <tr key={r.category}>
            <td className="max-w-[140px] truncate">{r.category}</td>
            <td className="text-right tabular-nums">{r.this_week.toLocaleString()}</td>
            <td className="text-right tabular-nums text-slate-500">{r.last_week.toLocaleString()}</td>
            <td className={`text-right font-medium tabular-nums ${r.change_pct === null ? "text-slate-400" : r.change_pct >= 15 ? "text-rose-600" : r.change_pct <= -15 ? "text-emerald-700" : "text-slate-600"}`}>
              {r.change_pct === null ? "new" : `${r.change_pct > 0 ? "+" : ""}${r.change_pct.toFixed(0)}%`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SimpleTable({ rows }: { rows: Breakdown[] }) {
  const total = rows.reduce((a, r) => a + r.count, 0);
  return (
    <table className="table-base">
      <thead><tr><th></th><th className="text-right">Tickets</th><th className="text-right">Share</th><th className="text-right">Negative</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <td>{r.name}</td>
            <td className="text-right tabular-nums">{r.count.toLocaleString()}</td>
            <td className="text-right tabular-nums text-slate-500">{pct(r.count / Math.max(total, 1))}</td>
            <td className="text-right tabular-nums text-slate-500">{pct(r.negative_share)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-5" aria-busy>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
      <Skeleton className="h-14" />
      <div className="grid gap-5 xl:grid-cols-2"><Skeleton className="h-80" /><Skeleton className="h-80" /></div>
    </div>
  );
}
