import { AlarmClock, CheckCircle2, Hourglass, PauseCircle, Timer } from "lucide-react";
import type { SlaState, SlaView } from "@/api/types";
import { Badge, Card, CardHeader, type Tone } from "@/components/ui";
import { fmtDateTime, fmtDuration, fmtRelative } from "@/lib/format";
import { liveState, useNow } from "@/lib/sla";

const LOOK: Record<SlaState, { tone: Tone; icon: typeof Timer; label: string }> = {
  none: { tone: "slate", icon: Hourglass, label: "No SLA" },
  running: { tone: "green", icon: Timer, label: "On track" },
  at_risk: { tone: "amber", icon: AlarmClock, label: "At risk" },
  breached: { tone: "red", icon: AlarmClock, label: "Breached" },
  paused: { tone: "slate", icon: PauseCircle, label: "Paused" },
  met: { tone: "green", icon: CheckCircle2, label: "SLA met" },
};

/** Green while on track, amber from 80 % of the target, red when breached; grey while waiting on the customer. */
export function SlaBadge({ sla, compact = false }: { sla: SlaView | null | undefined; compact?: boolean }) {
  const now = useNow();
  if (!sla || sla.state === "none") return compact ? <span className="text-xs text-slate-400">—</span> : null;
  const { state, remaining } = liveState(sla, now);
  const look = LOOK[state];
  const Icon = look.icon;
  const time =
    state === "breached" && remaining !== null ? `${fmtDuration(-remaining)} over`
      : state === "paused" ? "paused"
        : state === "met" ? "met"
          : remaining !== null ? `${fmtDuration(remaining)} left` : "";
  const title = sla.deadline ? `SLA ${look.label.toLowerCase()} · due ${fmtDateTime(sla.deadline)}${sla.policy ? ` · ${sla.policy.name}` : ""}` : look.label;
  return (
    <Badge tone={look.tone} title={title}>
      <Icon className="h-3 w-3" aria-hidden />
      <span className="tabular-nums">{compact ? time : `${look.label}${time && state !== "paused" && state !== "met" ? ` · ${time}` : ""}`}</span>
    </Badge>
  );
}

/** Sidebar card on the ticket workspace. */
export function SlaCard({ sla }: { sla: SlaView | null }) {
  const now = useNow();
  if (!sla || sla.state === "none") {
    return (
      <Card>
        <CardHeader title="SLA" icon={<Timer className="h-4 w-4" />} />
        <p className="px-4 py-3 text-sm text-slate-500">The clock starts when triage has set the priority.</p>
      </Card>
    );
  }
  const { state, remaining } = liveState(sla, now);
  const used = sla.target_seconds && remaining !== null ? Math.min(1, Math.max(0, 1 - remaining / sla.target_seconds)) : 1;
  const bar = state === "breached" ? "bg-rose-500" : state === "at_risk" ? "bg-amber-500" : state === "paused" ? "bg-slate-400" : "bg-emerald-500";
  return (
    <Card>
      <CardHeader title="SLA" icon={<Timer className="h-4 w-4" />} subtitle={sla.policy?.name} actions={<SlaBadge sla={sla} compact />} />
      <div className="space-y-3 px-4 py-3 text-sm">
        <div aria-label="SLA used" role="progressbar" aria-valuenow={Math.round(used * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className={`h-full ${bar}`} style={{ width: `${Math.round(used * 100)}%` }} /></div>
          <p className="mt-1 text-xs text-slate-500">{Math.round(used * 100)}% of {fmtDuration(sla.target_seconds ?? 0)} used</p>
        </div>
        <dl className="space-y-1.5 text-xs">
          <Row k="Due" v={sla.deadline ? fmtDateTime(sla.deadline) : "—"} />
          <Row k="Started" v={sla.started_at ? `${fmtDateTime(sla.started_at)}` : "—"} />
          {sla.paused && <Row k="Paused" v="Waiting on the customer — the deadline moves out" />}
          {sla.warned_at && <Row k="Warned" v={`${fmtRelative(sla.warned_at)} (80 %)`} />}
          {sla.breached_at && <Row k="Breached" v={fmtDateTime(sla.breached_at)} tone="text-rose-700" />}
        </dl>
      </div>
    </Card>
  );
}

function Row({ k, v, tone }: { k: string; v: string; tone?: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-500">{k}</dt>
      <dd className={`text-right ${tone ?? "text-slate-800"}`}>{v}</dd>
    </div>
  );
}
