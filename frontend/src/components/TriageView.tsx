import { Info } from "lucide-react";
import type { Entities, Priority, PriorityReason } from "@/api/types";
import { ConfidenceMeter, PriorityBadge, SentimentBadge } from "@/components/Badges";
import { Badge } from "@/components/ui";

interface Props {
  category: string | null;
  categoryConfidence: number | null;
  intent: string | null;
  intentConfidence: number | null;
  sentiment: string | null;
  sentimentScore: number | null;
  priority: Priority;
  reasons: PriorityReason[] | null;
  entities: Entities | null;
  topCategories?: [string, number][];
}

export function TriageView(p: Props) {
  const e = p.entities;
  const hasEntities = !!e && (e.amounts.length + e.order_ids.length + e.dates.length + e.products.length > 0 || e.repeat_contact);
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Category">
          <p className="truncate font-medium text-slate-900">{p.category ?? "—"}</p>
          <ConfidenceMeter value={p.categoryConfidence} />
        </Stat>
        <Stat label="Intent">
          <p className="truncate font-medium text-slate-900">{p.intent ?? "—"}</p>
          <ConfidenceMeter value={p.intentConfidence} />
        </Stat>
        <Stat label="Sentiment">
          <SentimentBadge sentiment={p.sentiment} />
          {p.sentimentScore !== null && <p className="mt-1 text-xs text-slate-500">{p.sentimentScore.toFixed(1)} / 5 stars</p>}
        </Stat>
        <Stat label="Priority"><PriorityBadge priority={p.priority} /></Stat>
      </dl>

      {p.topCategories && p.topCategories.length > 1 && (
        <p className="text-xs text-slate-500">
          Alternatives: {p.topCategories.slice(1).map(([c, v]) => `${c} (${Math.round(v * 100)}%)`).join(", ")}
        </p>
      )}

      {hasEntities && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-slate-500">Extracted entities</p>
          <div className="flex flex-wrap gap-1.5">
            {e!.amounts.map((a) => <Badge key={a.text} tone="green">{a.text}</Badge>)}
            {e!.order_ids.map((o) => <Badge key={o} tone="blue">Order {o}</Badge>)}
            {e!.dates.map((d) => <Badge key={d} tone="slate">{d}</Badge>)}
            {e!.products.map((x) => <Badge key={x} tone="teal">{x}</Badge>)}
            {e!.repeat_contact && <Badge tone="amber">Repeat contact</Badge>}
          </div>
        </div>
      )}

      {p.reasons && p.reasons.length > 0 && (
        <div>
          <p className="mb-1.5 flex items-center gap-1 text-xs font-medium text-slate-500">
            <Info className="h-3 w-3" /> Why {p.priority}? Business rules — they can only raise priority, never lower it.
          </p>
          <ol className="space-y-1">
            {p.reasons.map((r, i) => (
              <li key={`${r.rule}-${i}`} className="flex items-center gap-2 text-xs text-slate-700">
                <span className="w-9 shrink-0 font-mono text-[10px] text-slate-400">{r.rule}</span>
                <span>{r.reason}</span>
                <span className="text-slate-400">{!r.from ? r.to : r.from === r.to ? `already ${r.to}` : `${r.from} → ${r.to}`}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="mb-1 text-xs text-slate-500">{label}</dt>
      <dd className="space-y-1">{children}</dd>
    </div>
  );
}
