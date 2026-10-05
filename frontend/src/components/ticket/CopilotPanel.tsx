import clsx from "clsx";
import { AlertTriangle, BookOpen, Bot, Check, ClipboardCopy, Lightbulb, ListChecks, RefreshCw, Send, Sparkles, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "@/api/http";
import { useAcceptDraft, useDiscardDraft, useDraftResponse } from "@/api/client";
import type { Analysis, GroundingRef, TicketDetail } from "@/api/types";
import { Badge, Button, Card, CardHeader, EmptyState, Input, Skeleton, Textarea } from "@/components/ui";
import { fmtDateTime, fmtRelative } from "@/lib/format";

const same = (a: string | null | undefined, b: string | null | undefined) => (a ?? "").split(/\s+/).join(" ").trim() === (b ?? "").split(/\s+/).join(" ").trim();

/**
 * The AI copilot: summary, likely root cause, key issues, next steps and a draft reply. The draft is never sent by
 * the AI — the agent edits it if needed and accepts it, which posts it as their comment (marked AI-assisted).
 */
export function CopilotPanel({ ticket }: { ticket: TicketDetail }) {
  const generate = useDraftResponse(ticket.id);
  const insight = ticket.copilot;
  const [dirty, setDirty] = useState(false);
  const [confirmRegenerate, setConfirmRegenerate] = useState(false);

  function regenerate() {
    if (insight?.draft_status === "pending" && dirty && !confirmRegenerate) return setConfirmRegenerate(true);
    setConfirmRegenerate(false);
    generate.mutate(undefined, { onSuccess: () => setDirty(false) });
  }

  return (
    <Card>
      <CardHeader
        title="AI copilot"
        icon={<Bot className="h-4 w-4 text-violet-500" />}
        subtitle={insight ? insightSubtitle(insight) : "Summary, likely root cause, next steps and a draft reply from the LLM"}
        actions={
          <Button size="sm" variant={insight ? "secondary" : "primary"} loading={generate.isPending} onClick={regenerate}
            icon={insight ? <RefreshCw className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}>
            {insight ? "Regenerate" : "Run copilot"}
          </Button>
        }
      />
      <div className="p-4">
        {generate.isError && <InsightError error={generate.error} />}
        {confirmRegenerate && (
          <div className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="alert">
            <AlertTriangle className="h-4 w-4" /> Regenerating replaces the draft and your edits.
            <Button size="sm" variant="secondary" onClick={regenerate}>Regenerate anyway</Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmRegenerate(false)}>Keep editing</Button>
          </div>
        )}
        {generate.isPending && !insight ? (
          <div className="space-y-2"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-1/2" /><Skeleton className="h-16" /></div>
        ) : !insight ? (
          <EmptyState title="No copilot output yet" description="Personal data is masked before the complaint is sent to the model." icon={<Bot className="h-6 w-6" />} />
        ) : (
          <div className="space-y-4 text-sm">
            <section>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Summary</h4>
              <p className="leading-relaxed text-slate-800">{insight.summary}</p>
            </section>
            {insight.root_cause && (
              <section className="rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2.5">
                <h4 className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-amber-800">
                  <Lightbulb className="h-3.5 w-3.5" /> Likely root cause
                  <span className="font-normal normal-case tracking-normal text-amber-700">— a hypothesis, verify before acting</span>
                </h4>
                <p className="leading-relaxed text-amber-950">{insight.root_cause}</p>
              </section>
            )}
            <section>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Key issues</h4>
              <div className="flex flex-wrap gap-1.5">{(insight.key_issues ?? []).map((k) => <Badge key={k} tone="amber">{k}</Badge>)}</div>
            </section>
            <section>
              <h4 className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500"><ListChecks className="h-3.5 w-3.5" /> Recommended actions</h4>
              <ol className="list-decimal space-y-1 pl-5 text-slate-800">{(insight.recommendations ?? []).map((a) => <li key={a}>{a}</li>)}</ol>
            </section>
            {insight.grounding && insight.grounding.length > 0 && <Grounding refs={insight.grounding} />}
            <DraftReply key={insight.id} ticket={ticket} insight={insight} onDirty={setDirty} />
          </div>
        )}
      </div>
    </Card>
  );
}

/** RAG: which help articles and past tickets the copilot was given; the ones it relied on are highlighted. */
function Grounding({ refs }: { refs: GroundingRef[] }) {
  return (
    <section aria-label="Sources">
      <h4 className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
        <BookOpen className="h-3.5 w-3.5" /> Grounded in
      </h4>
      <ul className="flex flex-wrap gap-1.5">
        {refs.map((r) => (
          <li key={r.ref}>
            <Link to={r.type === "article" ? `/knowledge/${r.id}` : `/tickets/${r.id}`}
              title={r.cited ? "Used by the copilot" : "Given to the copilot, not used"}
              className={clsx("inline-flex max-w-[260px] items-center gap-1 rounded-md px-2 py-0.5 text-xs ring-1 ring-inset",
                r.cited ? "bg-violet-50 text-violet-800 ring-violet-200" : "bg-white text-slate-500 ring-slate-200")}>
              {r.cited && <Check className="h-3 w-3 shrink-0" />}
              <span className="truncate">{r.type === "article" ? r.title : `${r.ticket_number} · ${r.title}`}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DraftReply({ ticket, insight, onDirty }: { ticket: TicketDetail; insight: Analysis; onDirty: (dirty: boolean) => void }) {
  const accept = useAcceptDraft(ticket.id);
  const discard = useDiscardDraft(ticket.id);
  const [text, setText] = useState(insight.draft_response ?? "");
  const [discarding, setDiscarding] = useState(false);
  const [reason, setReason] = useState("");
  const [copied, setCopied] = useState(false);
  const edited = !same(text, insight.draft_response);
  const error = accept.error ?? discard.error;

  if (insight.draft_status === "accepted") {
    return (
      <section className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2.5" aria-label="Accepted reply">
        <p className="mb-1 flex flex-wrap items-center gap-1.5 text-xs text-emerald-800">
          <Check className="h-3.5 w-3.5" /> Accepted by <b>{insight.reviewed_by?.name ?? "an agent"}</b>
          <time dateTime={insight.reviewed_at ?? undefined} title={fmtDateTime(insight.reviewed_at)}>{fmtRelative(insight.reviewed_at)}</time>
          · {insight.edited ? "edited before posting" : "posted as drafted"} · in the conversation below
        </p>
        <p className="whitespace-pre-wrap leading-relaxed text-emerald-950">{insight.final_response}</p>
      </section>
    );
  }
  if (insight.draft_status === "discarded") {
    return (
      <section className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs text-slate-600" aria-label="Discarded draft">
        <p className="flex flex-wrap items-center gap-1.5">
          <Trash2 className="h-3.5 w-3.5" /> Draft discarded by <b>{insight.reviewed_by?.name ?? "an agent"}</b> {fmtRelative(insight.reviewed_at)}
          {insight.discard_reason && <>— “{insight.discard_reason}”</>}
        </p>
        <p className="mt-1">Press Regenerate for a new draft.</p>
      </section>
    );
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (text.trim()) accept.mutate({ analysisId: insight.id, response: text.trim() });
  }

  return (
    <section aria-label="Draft reply">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Draft reply {edited && <Badge tone="blue">Edited</Badge>}
        </h4>
        <button type="button" className="flex items-center gap-1 text-xs text-brand-600 hover:underline"
          onClick={() => { void navigator.clipboard?.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
          {copied ? <Check className="h-3.5 w-3.5" /> : <ClipboardCopy className="h-3.5 w-3.5" />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <form onSubmit={submit}>
        <label htmlFor={`draft-${insight.id}`} className="sr-only">Reply to the customer</label>
        <Textarea id={`draft-${insight.id}`} rows={7} value={text} maxLength={10_000} className="leading-relaxed"
          onChange={(e) => { setText(e.target.value); onDirty(!same(e.target.value, insight.draft_response)); }} />
        <p className="mt-1 text-xs text-slate-500">Nothing is sent until you accept. Accepting posts this text as your comment, marked AI-assisted.</p>
        {error && <p className="mt-2 text-xs text-rose-700" role="alert">{error instanceof ApiError ? error.message : "Something went wrong."}</p>}
        {discarding ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Input aria-label="Why discard? (optional)" placeholder="Why? (optional, helps improve the prompt)" className="h-8 max-w-xs text-xs"
              value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
            <Button type="button" size="sm" variant="danger" loading={discard.isPending}
              onClick={() => discard.mutate({ analysisId: insight.id, reason: reason.trim() || undefined })}>Discard draft</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setDiscarding(false)}>Cancel</Button>
          </div>
        ) : (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button type="submit" size="sm" icon={<Send className="h-3.5 w-3.5" />} loading={accept.isPending} disabled={!text.trim() || discard.isPending}>
              {edited ? "Accept edited reply" : "Accept & post reply"}
            </Button>
            <Button type="button" size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setDiscarding(true)} disabled={accept.isPending}>
              Discard
            </Button>
          </div>
        )}
      </form>
    </section>
  );
}

function insightSubtitle(insight: Analysis): string {
  const parts = [insight.provider === "openai" ? "OpenAI" : "Mock LLM", insight.model ?? "", insight.prompt_version ?? "", fmtRelative(insight.created_at)];
  if (insight.usage) {
    parts.push(`${insight.usage.total_tokens.toLocaleString()} tokens`, `~$${insight.usage.estimated_cost_usd.toFixed(4)}`);
  }
  return parts.filter(Boolean).join(" · ");
}

const ERROR_TITLES: Record<string, string> = {
  llm_auth_failed: "OpenAI API key rejected",
  llm_not_configured: "OpenAI is not configured",
  llm_rate_limited: "OpenAI rate limit reached",
  llm_quota_exceeded: "OpenAI quota exhausted",
  llm_timeout: "OpenAI timed out",
  llm_unreachable: "Can't reach OpenAI",
  llm_model_not_found: "OpenAI model not found",
  llm_invalid_output: "The model's answer was malformed",
  network_error: "Backend unreachable",
};

/** Clear, non-crashing message for a failed copilot request. The previous output (if any) stays visible. */
function InsightError({ error }: { error: Error }) {
  const api = error instanceof ApiError ? error : undefined;
  const title = (api?.code && ERROR_TITLES[api.code]) || "Couldn't run the copilot";
  return (
    <div className="mb-4 flex gap-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm" role="alert">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" aria-hidden />
      <div>
        <p className="font-medium text-rose-800">{title}</p>
        <p className="text-rose-700">{error.message}</p>
        {api?.retryAfter && <p className="mt-0.5 text-xs text-rose-600">You can retry in {api.retryAfter} s.</p>}
      </div>
    </div>
  );
}
