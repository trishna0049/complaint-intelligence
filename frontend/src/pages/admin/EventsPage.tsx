import clsx from "clsx";
import { Activity, ExternalLink, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useDeadLetters, useDiscardDeadLetter, usePipelineStatus, useReplayDeadLetter } from "@/api/client";
import type { DeadLetter } from "@/api/types";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { fmtDateTime, fmtRelative } from "@/lib/format";

type DlqView = "waiting" | "replayed" | "discarded";
const VIEWS: { id: DlqView; label: string }[] = [
  { id: "waiting", label: "Waiting" },
  { id: "replayed", label: "Replayed" },
  { id: "discarded", label: "Discarded" },
];

/** Admin: the Kafka event pipeline — outbox lag, what each worker processed, and the dead-letter queue. */
export function EventsPage() {
  const status = usePipelineStatus();
  const [view, setView] = useState<DlqView>("waiting");
  const s = status.data;

  return (
    <>
      <PageHeader
        title="Event pipeline"
        description="Changes are saved with their events (outbox), published to Kafka and processed by four workers. Failed events retry, then wait here."
        actions={s?.kafka_ui_url ? (
          <a href={s.kafka_ui_url} target="_blank" rel="noreferrer">
            <Button variant="secondary" icon={<ExternalLink className="h-4 w-4" />}>Kafka UI</Button>
          </a>
        ) : undefined}
      />
      {status.error ? <Card><ErrorState error={status.error} onRetry={() => void status.refetch()} /></Card> : !s ? (
        <div className="grid gap-4 md:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20" />)}</div>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-4 md:grid-cols-4">
            <Tile label="Mode" value={s.mode === "kafka" ? "Kafka" : "Inline"} hint={s.kafka_bootstrap_servers ?? "handlers run in the API process"} />
            <Tile label="Outbox waiting" value={s.outbox.pending.toLocaleString()} warn={s.outbox.pending > 50}
              hint={s.outbox.oldest_pending_seconds !== null ? `oldest ${Math.round(s.outbox.oldest_pending_seconds)} s` : "all published"} />
            <Tile label="Publish failures" value={s.outbox.failing.toLocaleString()} warn={s.outbox.failing > 0}
              hint={s.outbox.last_published_at ? `last published ${fmtRelative(s.outbox.last_published_at)}` : "nothing published yet"} />
            <Tile label="Dead letters" value={s.consumers.reduce((n, c) => n + c.dead_letters_waiting, 0).toLocaleString()}
              warn={s.consumers.some((c) => c.dead_letters_waiting > 0)} hint={`after ${s.retries} retries`} />
          </div>
          <Card className="mb-5">
            <CardHeader title="Workers" icon={<Activity className="h-4 w-4" />} subtitle={`Consumer groups ${s.prefix}.<worker>`} />
            <div className="overflow-x-auto">
              <table className="table-base" aria-label="Workers">
                <thead><tr><th>Worker</th><th>Consumes</th><th className="text-right">Last hour</th><th className="text-right">Total</th><th>Last event</th><th className="text-right">Dead letters</th></tr></thead>
                <tbody>
                  {s.consumers.map((c) => (
                    <tr key={c.name}>
                      <td><p className="font-medium text-slate-900">{c.name}</p><p className="text-xs text-slate-500">{c.description}</p></td>
                      <td><div className="flex flex-wrap gap-1">{c.events.map((e) => <Badge key={e} tone="slate">{e}</Badge>)}</div></td>
                      <td className="text-right tabular-nums">{c.processed_last_hour.toLocaleString()}</td>
                      <td className="text-right tabular-nums">{c.processed_total.toLocaleString()}</td>
                      <td className="whitespace-nowrap text-xs text-slate-500">{c.last_processed_at ? fmtRelative(c.last_processed_at) : "—"}</td>
                      <td className="text-right">{c.dead_letters_waiting > 0 ? <Badge tone="red">{c.dead_letters_waiting}</Badge> : <span className="text-slate-400">0</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
      <Card>
        <div className="flex gap-1 border-b border-slate-100 px-3 pt-2" role="tablist" aria-label="Dead letters">
          {VIEWS.map((v) => (
            <button key={v.id} role="tab" aria-selected={view === v.id} onClick={() => setView(v.id)}
              className={clsx("-mb-px border-b-2 px-3 py-2 text-sm font-medium", view === v.id ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800")}>
              {v.label}
            </button>
          ))}
        </div>
        <DeadLetters view={view} />
      </Card>
    </>
  );
}

function Tile({ label, value, hint, warn }: { label: string; value: string; hint?: string; warn?: boolean }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className={clsx("mt-1 text-2xl font-semibold tracking-tight", warn ? "text-rose-600" : "text-slate-900")}>{value}</p>
      {hint && <p className="truncate text-xs text-slate-500" title={hint}>{hint}</p>}
    </Card>
  );
}

function DeadLetters({ view }: { view: DlqView }) {
  const { data, isLoading, error, refetch } = useDeadLetters(view);
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (isLoading || !data) return <div className="space-y-2 p-4"><Skeleton className="h-14" /><Skeleton className="h-14" /></div>;
  if (data.items.length === 0) {
    return <EmptyState title={view === "waiting" ? "No failed events" : `Nothing ${view}`} description={view === "waiting" ? "Every event was processed." : undefined} />;
  }
  return <ul className="divide-y divide-slate-100" aria-label={`${view} dead letters`}>{data.items.map((d) => <DeadLetterRow key={d.id} letter={d} />)}</ul>;
}

function DeadLetterRow({ letter: d }: { letter: DeadLetter }) {
  const replay = useReplayDeadLetter();
  const discard = useDiscardDeadLetter();
  const error = replay.error ?? discard.error;
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge tone="violet">{d.consumer}</Badge>
            <span className="font-mono text-slate-700">{d.event_type}</span>
            {d.ticket_id && <Link to={`/tickets/${d.ticket_id}`} className="text-brand-600 hover:underline">ticket #{d.ticket_id}</Link>}
            <span className="text-slate-500" title={fmtDateTime(d.failed_at)}>failed {fmtRelative(d.failed_at)} after {d.attempts} attempts</span>
          </div>
          <p className="mt-1 break-words font-mono text-xs text-rose-700">{d.error}</p>
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-slate-500">Event {d.event_id}</summary>
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-slate-50 p-2 text-[11px] text-slate-700">{JSON.stringify(d.envelope, null, 2)}</pre>
          </details>
        </div>
        {d.status === "waiting" ? (
          <div className="flex gap-2">
            <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={replay.isPending} disabled={discard.isPending || d.event_type === "unreadable"}
              onClick={() => replay.mutate(d.id)}>Replay</Button>
            <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} loading={discard.isPending} disabled={replay.isPending}
              onClick={() => discard.mutate(d.id)}>Discard</Button>
          </div>
        ) : (
          <Badge tone={d.status === "replayed" ? "green" : "slate"}>{d.status} {d.resolved_at ? fmtRelative(d.resolved_at) : ""}</Badge>
        )}
      </div>
      {error && <p className="mt-1 text-xs text-rose-700" role="alert">{error.message}</p>}
    </li>
  );
}
