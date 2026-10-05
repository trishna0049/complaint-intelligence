import { ArrowUpCircle, CheckCircle2, Clock, Lock, Play, RotateCcw, UserPlus } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { ApiError } from "@/api/http";
import { useAssign, useClose, useEscalate, useReopen, useResolve, useTeamMembers, useTeams, useUpdateTicket } from "@/api/client";
import type { TicketAction, TicketDetail } from "@/api/types";
import { useAuth } from "@/auth/useAuth";
import { Avatar, Badge, Button, Field, Modal, Select, Spinner, Textarea } from "@/components/ui";
import { ACTION_LABELS } from "@/lib/status";

const ICONS: Record<TicketAction, ReactNode> = {
  assign: <UserPlus className="h-4 w-4" />,
  start: <Play className="h-4 w-4" />,
  wait_customer: <Clock className="h-4 w-4" />,
  resume: <Play className="h-4 w-4" />,
  escalate: <ArrowUpCircle className="h-4 w-4" />,
  resolve: <CheckCircle2 className="h-4 w-4" />,
  close: <Lock className="h-4 w-4" />,
  reopen: <RotateCcw className="h-4 w-4" />,
};

// The order buttons appear in; the most common next step is the primary button.
const ORDER: TicketAction[] = ["start", "resume", "resolve", "close", "assign", "wait_customer", "escalate", "reopen"];

function errorMessage(err: unknown): string | null {
  if (!err) return null;
  return err instanceof ApiError ? err.message : "Something went wrong.";
}

/** Only the actions the API says are allowed for this user right now (state machine + permissions). */
export function ActionBar({ ticket }: { ticket: TicketDetail }) {
  const [open, setOpen] = useState<TicketAction | null>(null);
  const patch = useUpdateTicket(ticket.id);
  const close = useClose(ticket.id);
  const actions = ORDER.filter((a) => ticket.allowed_actions.includes(a));
  const direct = { start: "IN_PROGRESS", resume: "IN_PROGRESS", wait_customer: "WAITING_CUSTOMER" } as const;
  const busy = patch.isPending || close.isPending;
  const error = errorMessage(patch.error ?? close.error);

  function run(a: TicketAction) {
    if (a === "start" || a === "resume" || a === "wait_customer") patch.mutate({ status: direct[a] });
    else if (a === "close") close.mutate(undefined);
    else setOpen(a);
  }

  if (actions.length === 0) {
    return <p className="text-xs text-slate-500">No actions available to you on this ticket.</p>;
  }
  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex flex-wrap justify-end gap-2" role="toolbar" aria-label="Ticket actions">
        {actions.map((a, i) => (
          <Button key={a} size="sm" variant={i === 0 ? "primary" : a === "escalate" ? "danger" : "secondary"} icon={ICONS[a]}
            onClick={() => run(a)} disabled={busy}>
            {ACTION_LABELS[a]}
          </Button>
        ))}
      </div>
      {error && <p className="text-xs text-rose-700" role="alert">{error}</p>}
      {open === "assign" && <AssignModal ticket={ticket} onClose={() => setOpen(null)} />}
      {open === "escalate" && <ReasonModal ticket={ticket} kind="escalate" onClose={() => setOpen(null)} />}
      {open === "reopen" && <ReasonModal ticket={ticket} kind="reopen" onClose={() => setOpen(null)} />}
      {open === "resolve" && <ResolveModal ticket={ticket} onClose={() => setOpen(null)} />}
    </div>
  );
}

function AssignModal({ ticket, onClose }: { ticket: TicketDetail; onClose: () => void }) {
  const { user } = useAuth();
  const isAdmin = user?.role === "ADMIN";
  const teams = useTeams();
  const [teamId, setTeamId] = useState<number | null>(ticket.team?.id ?? user?.team?.id ?? null);
  const members = useTeamMembers(isAdmin ? teamId : user?.team?.id);
  const assign = useAssign(ticket.id);
  const [assignee, setAssignee] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const leastBusy = members.data?.filter((m) => m.role === "AGENT").reduce<number | null>(
    (best, m) => (best === null || m.open_tickets < (members.data!.find((x) => x.id === best)?.open_tickets ?? Infinity) ? m.id : best), null);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (assignee) assign.mutate({ assignee_id: assignee, note: note.trim() || undefined }, { onSuccess: onClose });
  }

  return (
    <Modal open title={`Assign ${ticket.ticket_number}`} onClose={onClose} wide
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="assign-form" loading={assign.isPending} disabled={!assignee}>Assign</Button>
      </>}>
      <form id="assign-form" onSubmit={submit} className="space-y-3">
        {assign.error && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">{errorMessage(assign.error)}</p>}
        {isAdmin ? (
          <Field label="Team" htmlFor="assign-team">
            <Select id="assign-team" value={teamId ?? ""} onChange={(e) => { setTeamId(Number(e.target.value) || null); setAssignee(null); }}>
              <option value="">Choose a team…</option>
              {teams.data?.map((t) => <option key={t.id} value={t.id}>{t.name}{t.id === ticket.team?.id ? " (current)" : ""}</option>)}
            </Select>
          </Field>
        ) : (
          <p className="text-xs text-slate-500">You can assign within {user?.team?.name ?? "your team"}. Moving a ticket to another team needs an Admin.</p>
        )}
        <div>
          <p className="mb-1 text-xs font-medium text-slate-700">Agent <span className="font-normal text-slate-500">— open tickets in brackets</span></p>
          {members.isLoading ? (
            <div className="flex items-center gap-2 py-4 text-sm text-slate-500"><Spinner className="h-4 w-4" /> Loading team…</div>
          ) : !members.data?.length ? (
            <p className="py-3 text-sm text-slate-500">{teamId || !isAdmin ? "This team has no active members." : "Choose a team first."}</p>
          ) : (
            <ul className="max-h-64 divide-y divide-slate-100 overflow-y-auto rounded-md border border-slate-200" role="radiogroup" aria-label="Agent">
              {[...members.data].sort((a, b) => a.open_tickets - b.open_tickets || a.name.localeCompare(b.name)).map((m) => (
                <li key={m.id}>
                  <label className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm hover:bg-slate-50">
                    <input type="radio" name="assignee" className="text-brand-600" checked={assignee === m.id} onChange={() => setAssignee(m.id)}
                      aria-label={m.name} />
                    <Avatar name={m.name} size="sm" />
                    <span className="flex-1 text-slate-800">{m.name}{m.id === user?.id ? " (you)" : ""}</span>
                    {m.id === leastBusy && <Badge tone="green">Least busy</Badge>}
                    {m.id === ticket.assignee?.id && <Badge tone="blue">Current</Badge>}
                    <span className="w-8 text-right tabular-nums text-xs text-slate-500">({m.open_tickets})</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
        <Field label="Note (optional)" htmlFor="assign-note">
          <Textarea id="assign-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        </Field>
      </form>
    </Modal>
  );
}

function ReasonModal({ ticket, kind, onClose }: { ticket: TicketDetail; kind: "escalate" | "reopen"; onClose: () => void }) {
  const escalate = useEscalate(ticket.id);
  const reopen = useReopen(ticket.id);
  const mutation = kind === "escalate" ? escalate : reopen;
  const [reason, setReason] = useState("");
  const [local, setLocal] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (reason.trim().length < 3) return setLocal("Give a reason (at least 3 characters).");
    setLocal(null);
    mutation.mutate(reason.trim(), { onSuccess: onClose });
  }

  const title = kind === "escalate" ? `Escalate ${ticket.ticket_number}` : `Reopen ${ticket.ticket_number}`;
  return (
    <Modal open title={title} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="reason-form" variant={kind === "escalate" ? "danger" : "primary"} loading={mutation.isPending}>
          {kind === "escalate" ? "Escalate" : "Reopen"}
        </Button>
      </>}>
      <form id="reason-form" onSubmit={submit} noValidate className="space-y-3">
        {(local || mutation.error) && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">{local ?? errorMessage(mutation.error)}</p>}
        <p className="text-sm text-slate-600">
          {kind === "escalate" ? "Admins are alerted. The ticket stays visible to its team." : "The ticket goes back to its agent (or the triaged pool)."}
        </p>
        <Field label="Reason" htmlFor="reason">
          <Textarea id="reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />
        </Field>
      </form>
    </Modal>
  );
}

function ResolveModal({ ticket, onClose }: { ticket: TicketDetail; onClose: () => void }) {
  const resolve = useResolve(ticket.id);
  const [text, setText] = useState("");
  const [local, setLocal] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (text.trim().length < 3) return setLocal("Describe what was done (at least 3 characters).");
    setLocal(null);
    resolve.mutate(text.trim(), { onSuccess: onClose });
  }

  return (
    <Modal open title={`Resolve ${ticket.ticket_number}`} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="resolve-form" loading={resolve.isPending} icon={<CheckCircle2 className="h-4 w-4" />}>Resolve</Button>
      </>}>
      <form id="resolve-form" onSubmit={submit} noValidate className="space-y-3">
        {(local || resolve.error) && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">{local ?? errorMessage(resolve.error)}</p>}
        <Field label="Resolution" htmlFor="resolution" hint="Shown on the ticket and in the timeline.">
          <Textarea id="resolution" rows={4} value={text} onChange={(e) => setText(e.target.value)} maxLength={5000}
            placeholder="e.g. Confirmed the duplicate debit and raised a reversal of ₹12,500 (ref RV-88213)." />
        </Field>
      </form>
    </Modal>
  );
}
