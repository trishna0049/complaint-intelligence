import { ArrowUpCircle, Bot, CheckCircle2, Clock, FilePlus2, History, Inbox, MessageSquare, PencilLine, PlusCircle, Route, ShieldQuestion, Sparkles, UserPlus } from "lucide-react";
import type { ReactNode } from "react";
import type { TimelineEvent } from "@/api/types";
import { Card, CardHeader } from "@/components/ui";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { statusLabel } from "@/lib/status";

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));

function describe(e: TimelineEvent): { icon: ReactNode; text: ReactNode; detail?: string } {
  const m = e.metadata ?? {};
  // Moves made by the routing rules carry a trigger; only an Admin's "Auto-assign" (trigger "manual") is a person's.
  const byRules = (e.event_type === "routed" || !!m.trigger) && m.trigger !== "manual";
  const who = byRules ? "Routing rules" : e.actor?.name ?? (e.event_type === "triaged" ? "AI triage" : "System");
  switch (e.event_type) {
    case "created":
      return { icon: <PlusCircle className="h-3.5 w-3.5" />, text: <>{m.historical ? "Contact received" : <><b>{who}</b> created the ticket</>} via {str(m.channel)}</> };
    case "triaged":
      return {
        icon: <Sparkles className="h-3.5 w-3.5 text-violet-500" />,
        text: <>AI triage: <b>{str(m.category)}</b> · {str(m.priority)}{m.confidence != null ? ` · ${Math.round(Number(m.confidence) * 100)}% confidence` : ""}</>,
        detail: m.needs_review ? "Low confidence — flagged for review" : str(m.model_version),
      };
    case "assigned":
      return {
        icon: <UserPlus className="h-3.5 w-3.5" />,
        text: e.actor && e.actor.id === m.assignee_id ? <><b>{who}</b> took the ticket</> : <><b>{who}</b> assigned it to <b>{str(m.assignee)}</b></>,
        detail: str(m.note) || undefined,
      };
    case "status_changed": {
      const reason = str(m.reason || m.resolution);
      if (m.historical) {
        return { icon: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />, text: <>Closed by <b>{who}</b>{m.csat ? ` · CSAT ${str(m.csat)}/5` : ""}</> };
      }
      return {
        icon: m.to === "RESOLVED" || m.to === "CLOSED" ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <Clock className="h-3.5 w-3.5" />,
        text: <><b>{who}</b> moved it from {statusLabel(str(m.from))} to <b>{statusLabel(str(m.to))}</b></>,
        detail: reason || undefined,
      };
    }
    case "escalated":
      return { icon: <ArrowUpCircle className="h-3.5 w-3.5 text-rose-600" />, text: <>{m.auto ? <b>SLA engine</b> : <b>{who}</b>} escalated the ticket</>, detail: str(m.reason) };
    case "comment_added":
      return { icon: <MessageSquare className="h-3.5 w-3.5" />, text: <><b>{who}</b> {m.ai_assisted ? "posted the AI-drafted reply" : "commented"}</> };
    case "attachment_added":
      return { icon: <FilePlus2 className="h-3.5 w-3.5" />, text: <><b>{who}</b> attached {str(m.filename)}</> };
    case "routed": {
      const by = byRules ? <><b>Routing rules</b>: </> : <><b>{who}</b> re-ran routing: </>;
      const reason = str(m.reason);
      switch (m.outcome) {
        case "assigned":
          return { icon: <Route className="h-3.5 w-3.5 text-brand-600" />, text: <>{by}assigned to <b>{str(m.assignee)}</b> in {str(m.team)}</>, detail: reason };
        case "team_queue":
          return { icon: <Inbox className="h-3.5 w-3.5 text-amber-600" />, text: <>{by}queued for <b>{str(m.team)}</b></>, detail: reason };
        case "review":
          return { icon: <ShieldQuestion className="h-3.5 w-3.5 text-violet-500" />, text: <>{by}waiting for a category review</>, detail: reason };
        default:
          return { icon: <Route className="h-3.5 w-3.5" />, text: <>{by}not routed</>, detail: reason };
      }
    }
    case "category_confirmed":
      return { icon: <CheckCircle2 className="h-3.5 w-3.5 text-violet-500" />, text: <><b>{who}</b> confirmed the AI category <b>{str(m.category)}</b></> };
    case "category_corrected":
      return {
        icon: <PencilLine className="h-3.5 w-3.5" />,
        text: <><b>{who}</b> changed the category from {str(m.from)} to <b>{str(m.to)}</b></>,
        detail: m.priority_from !== m.priority_to ? `Priority ${str(m.priority_from)} → ${str(m.priority_to)} (rules)` : undefined,
      };
    case "copilot_generated":
      return { icon: <Bot className="h-3.5 w-3.5 text-violet-500" />, text: <><b>{who}</b> ran the AI copilot</> };
    case "first_response":
      return { icon: <MessageSquare className="h-3.5 w-3.5" />, text: <>First response by <b>{who}</b></> };
    default:
      return { icon: <History className="h-3.5 w-3.5" />, text: <><b>{who}</b> · {e.event_type.replace(/_/g, " ")}</> };
  }
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  const historical = events.some((e) => e.metadata?.historical);
  return (
    <Card>
      <CardHeader title="Timeline" icon={<History className="h-4 w-4" />} subtitle={historical ? "Historical record — real timestamps from the dataset" : "Every change, oldest first"} />
      {events.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-slate-500">No events yet.</p>
      ) : (
        <ol aria-label="Ticket timeline" className="relative space-y-3 px-4 py-3 before:absolute before:bottom-4 before:left-[27px] before:top-4 before:w-px before:bg-slate-200">
          {events.map((e) => {
            const d = describe(e);
            return (
              <li key={e.id} className="relative flex gap-3">
                <span className="z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500">{d.icon}</span>
                <div className="min-w-0 text-xs">
                  <p className="text-slate-700">{d.text}</p>
                  {d.detail && <p className="mt-0.5 whitespace-pre-wrap text-slate-500">{d.detail}</p>}
                  <time className="text-slate-400" dateTime={e.created_at} title={fmtDateTime(e.created_at)}>{fmtRelative(e.created_at)}</time>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
