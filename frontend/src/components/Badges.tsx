import { AlertOctagon, ArrowDown, ArrowUp, Minus } from "lucide-react";
import type { Priority, Status } from "@/api/types";
import { Badge, type Tone } from "@/components/ui";
import { SENTIMENT_COLORS } from "@/lib/colors";
import { statusLabel } from "@/lib/status";

const PRIORITY: Record<Priority, { tone: Tone; icon: typeof ArrowUp }> = {
  Critical: { tone: "red", icon: AlertOctagon },
  High: { tone: "amber", icon: ArrowUp },
  Medium: { tone: "blue", icon: Minus },
  Low: { tone: "slate", icon: ArrowDown },
};

export function PriorityBadge({ priority }: { priority: Priority }) {
  const p = PRIORITY[priority] ?? PRIORITY.Medium;
  const Icon = p.icon;
  return (
    <Badge tone={p.tone}>
      <Icon className="h-3 w-3" aria-hidden />
      {priority}
    </Badge>
  );
}

const SENTIMENT_TONE: Record<string, Tone> = {
  "Very Negative": "red",
  Negative: "amber",
  Neutral: "slate",
  Positive: "blue",
  "Very Positive": "teal",
};

export function SentimentBadge({ sentiment }: { sentiment: string | null }) {
  if (!sentiment) return <span className="text-xs text-slate-400">—</span>;
  return (
    <Badge tone={SENTIMENT_TONE[sentiment] ?? "slate"}>
      <span className="h-2 w-2 rounded-full" style={{ background: SENTIMENT_COLORS[sentiment] }} aria-hidden />
      {sentiment}
    </Badge>
  );
}

const STATUS_TONE: Record<Status, Tone> = {
  NEW: "slate",
  TRIAGED: "violet",
  ASSIGNED: "blue",
  IN_PROGRESS: "brand",
  WAITING_CUSTOMER: "amber",
  ESCALATED: "red",
  RESOLVED: "green",
  CLOSED: "slate",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <Badge tone={STATUS_TONE[status] ?? "slate"} dot>
      {statusLabel(status)}
    </Badge>
  );
}

export function ConfidenceMeter({ value, label = "Model confidence" }: { value: number | null; label?: string }) {
  if (value === null || value === undefined) return <span className="text-xs text-slate-400">—</span>;
  const pct = Math.round(value * 100);
  const color = value >= 0.7 ? "bg-emerald-500" : value >= 0.45 ? "bg-amber-500" : "bg-rose-500";
  return (
    <span className="inline-flex items-center gap-1.5" title={`${label}: ${pct}%`}>
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-slate-200">
        <span className={`block h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="text-xs tabular-nums text-slate-600">{pct}%</span>
    </span>
  );
}
