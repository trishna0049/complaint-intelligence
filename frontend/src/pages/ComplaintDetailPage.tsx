import { ArrowLeft, Bot, Check, ClipboardCopy, FileText, ListChecks, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, useCategories, useComplaint, useGenerateInsight, useUpdateComplaint } from "@/api/client";
import type { ComplaintDetail } from "@/api/types";
import { PriorityBadge, StatusBadge } from "@/components/Badges";
import { TriageView } from "@/components/TriageView";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, LoadingState, Select, Skeleton } from "@/components/ui";
import { fmtDateTime, fmtInr, fmtRelative } from "@/lib/format";

export function ComplaintDetailPage() {
  const id = Number(useParams().id);
  const { data: c, isLoading, error, refetch } = useComplaint(id);

  if (isLoading) return <LoadingState label="Loading complaint…" />;
  if (error) {
    return (
      <Card>
        {error instanceof ApiError && error.status === 404 ? (
          <EmptyState title="Complaint not found" action={<Link to="/complaints" className="text-sm text-brand-600 hover:underline">Back to complaints</Link>} />
        ) : (
          <ErrorState error={error} onRetry={() => void refetch()} />
        )}
      </Card>
    );
  }
  if (!c) return null;

  return (
    <div>
      <Link to="/complaints" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> Complaints
      </Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm text-slate-500">{c.reference}</span>
            <StatusBadge status={c.status} />
            <PriorityBadge priority={c.priority} />
            {c.needs_review && <Badge tone="violet"><Sparkles className="h-3 w-3" /> Needs review</Badge>}
          </div>
          <h1 className="mt-1.5 text-xl font-semibold tracking-tight text-slate-900">{c.subject}</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            {fmtRelative(c.created_at)} via {c.channel}{c.customer_name && ` · ${c.customer_name}`}{c.city && ` · ${c.city}`}
          </p>
        </div>
        <StatusControl complaint={c} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader title="Complaint" icon={<FileText className="h-4 w-4" />} subtitle={fmtDateTime(c.created_at)}
              actions={c.text_is_template ? <Badge tone="slate" title="The source dataset row had no remark text">Templated text</Badge> : undefined} />
            <p className="whitespace-pre-wrap px-4 py-3 text-sm leading-relaxed text-slate-800">{c.text}</p>
          </Card>

          <Card>
            <CardHeader
              title="AI triage"
              icon={<Sparkles className="h-4 w-4 text-violet-500" />}
              subtitle={c.labels_from === "dataset" ? "Historical record — category and intent are the dataset's own labels" :
                c.labels_from === "human" ? "Category corrected by a person" : c.model_version ?? undefined}
            />
            <div className="p-4">
              <TriageView category={c.category} categoryConfidence={c.labels_from === "model" ? c.category_confidence : null}
                intent={c.intent} intentConfidence={c.labels_from === "model" ? c.intent_confidence : null}
                sentiment={c.sentiment} sentimentScore={c.sentiment_score} priority={c.priority} reasons={c.priority_reasons} entities={c.entities} />
              <CategoryCorrection complaint={c} />
            </div>
          </Card>

          <InsightPanel complaint={c} />
        </div>

        <aside className="space-y-5">
          <Card>
            <CardHeader title="Details" />
            <dl className="divide-y divide-slate-100 px-4 py-1 text-sm">
              {[
                ["Channel", c.channel],
                ["Customer", c.customer_name ?? "—"],
                ["Order", c.order_id ?? "—"],
                ["Product", c.product ?? "—"],
                ["Amount", fmtInr(c.amount_inr)],
                ["City", c.city ?? "—"],
                ["CSAT", c.csat_score ? `${c.csat_score} / 5` : "—"],
                ["Source", c.source === "dataset" ? "Historical dataset" : "Logged in app"],
                ["Resolved", fmtDateTime(c.resolved_at)],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 py-1.5">
                  <dt className="text-slate-500">{k}</dt>
                  <dd className="truncate text-right text-slate-800">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function StatusControl({ complaint }: { complaint: ComplaintDetail }) {
  const update = useUpdateComplaint(complaint.id);
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="status" className="text-xs text-slate-500">Status</label>
      <Select id="status" className="w-36" value={complaint.status} disabled={update.isPending}
        onChange={(e) => update.mutate({ status: e.target.value })}>
        {["Open", "In Progress", "Resolved"].map((s) => <option key={s}>{s}</option>)}
      </Select>
    </div>
  );
}

function CategoryCorrection({ complaint }: { complaint: ComplaintDetail }) {
  const categories = useCategories();
  const update = useUpdateComplaint(complaint.id);
  if (complaint.labels_from === "dataset") return null;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 text-xs text-slate-500">
      <span>Wrong category? Correct it (priority is recalculated by the rules):</span>
      <Select aria-label="Correct category" className="h-8 w-48 text-xs" value={complaint.category ?? ""}
        onChange={(e) => update.mutate({ category: e.target.value })} disabled={update.isPending}>
        {categories.data?.map((c) => <option key={c.name}>{c.name}</option>)}
      </Select>
      {update.isError && <span className="text-rose-600">{update.error.message}</span>}
    </div>
  );
}

function InsightPanel({ complaint }: { complaint: ComplaintDetail }) {
  const generate = useGenerateInsight(complaint.id);
  const [copied, setCopied] = useState(false);
  const insight = complaint.insight;

  return (
    <Card>
      <CardHeader
        title="AI insights"
        icon={<Bot className="h-4 w-4 text-violet-500" />}
        subtitle={insight ? `${insight.provider === "openai" ? "OpenAI" : "Mock LLM"} · ${insight.model} · ${insight.prompt_version} · ${fmtRelative(insight.created_at)}` : "Summary, key issues and recommended actions from the LLM"}
        actions={
          <Button size="sm" variant={insight ? "secondary" : "primary"} loading={generate.isPending} onClick={() => generate.mutate()}
            icon={insight ? <RefreshCw className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}>
            {insight ? "Regenerate" : "Generate insights"}
          </Button>
        }
      />
      <div className="p-4">
        {generate.isError && <p className="mb-3 text-sm text-rose-600" role="alert">{generate.error.message}</p>}
        {generate.isPending && !insight ? (
          <div className="space-y-2"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-1/2" /><Skeleton className="h-16" /></div>
        ) : !insight ? (
          <EmptyState title="No insights yet" description="Personal data is masked before the complaint is sent to the model." icon={<Bot className="h-6 w-6" />} />
        ) : (
          <div className="space-y-4 text-sm">
            <section>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Summary</h4>
              <p className="leading-relaxed text-slate-800">{insight.summary}</p>
            </section>
            <section>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Key issues</h4>
              <div className="flex flex-wrap gap-1.5">{insight.key_issues.map((k) => <Badge key={k} tone="amber">{k}</Badge>)}</div>
            </section>
            <section>
              <h4 className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500"><ListChecks className="h-3.5 w-3.5" /> Recommended actions</h4>
              <ol className="list-decimal space-y-1 pl-5 text-slate-800">{insight.recommended_actions.map((a) => <li key={a}>{a}</li>)}</ol>
            </section>
            <section>
              <div className="mb-1 flex items-center justify-between">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Suggested reply (draft — review before sending)</h4>
                <button className="flex items-center gap-1 text-xs text-brand-600 hover:underline"
                  onClick={() => { void navigator.clipboard?.writeText(insight.customer_reply); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
                  {copied ? <Check className="h-3.5 w-3.5" /> : <ClipboardCopy className="h-3.5 w-3.5" />} {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <p className="whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-3 leading-relaxed text-slate-700">{insight.customer_reply}</p>
            </section>
          </div>
        )}
      </div>
    </Card>
  );
}
