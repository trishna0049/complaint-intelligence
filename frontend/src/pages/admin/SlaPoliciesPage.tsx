import { Plus, Timer, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError } from "@/api/http";
import { useCategories, useCreateSlaPolicy, useDeleteSlaPolicy, useSlaPolicies, useUpdateSlaPolicy } from "@/api/client";
import type { Priority, SlaPolicy } from "@/api/types";
import { PriorityBadge } from "@/components/Badges";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Select, Skeleton } from "@/components/ui";
import { fmtDuration } from "@/lib/format";

const PRIORITIES: Priority[] = ["Critical", "High", "Medium", "Low"];

/** Admin: resolution targets per priority, optionally per category (the more specific policy wins). */
export function SlaPoliciesPage() {
  const { data, isLoading, error, refetch } = useSlaPolicies();
  const [creating, setCreating] = useState(false);
  return (
    <>
      <PageHeader
        title="SLA policies"
        description="Resolution targets. A category-specific policy beats the priority's default. The clock pauses while a ticket waits on the customer; warnings fire at 80 %, breaches escalate automatically. Changes apply to clocks started afterwards."
        actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>New policy</Button>}
      />
      <Card>
        {error ? <ErrorState error={error} onRetry={() => void refetch()} /> : isLoading || !data ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : data.length === 0 ? <EmptyState title="No policies" /> : (
          <div className="overflow-x-auto">
            <table className="table-base" aria-label="SLA policies">
              <thead><tr><th>Policy</th><th>Priority</th><th>Category</th><th>Target</th><th>Status</th><th /></tr></thead>
              <tbody>{data.map((p) => <PolicyRow key={p.id} policy={p} />)}</tbody>
            </table>
          </div>
        )}
      </Card>
      {creating && <CreatePolicy onClose={() => setCreating(false)} />}
    </>
  );
}

function PolicyRow({ policy: p }: { policy: SlaPolicy }) {
  const update = useUpdateSlaPolicy();
  const remove = useDeleteSlaPolicy();
  const [minutes, setMinutes] = useState(String(p.target_minutes));
  const changed = Number(minutes) !== p.target_minutes && Number(minutes) > 0;
  const error = update.error ?? remove.error;
  return (
    <tr>
      <td>
        <p className="font-medium text-slate-900">{p.name}</p>
        {error && <p className="text-xs text-rose-700" role="alert">{error instanceof ApiError ? error.message : "Failed"}</p>}
      </td>
      <td><PriorityBadge priority={p.priority} /></td>
      <td>{p.category ?? <span className="text-slate-500">Default (every category)</span>}</td>
      <td>
        <div className="flex items-center gap-2">
          <Input aria-label={`Target minutes for ${p.name}`} type="number" min={1} className="h-8 w-24 text-xs" value={minutes}
            onChange={(e) => setMinutes(e.target.value)} />
          <span className="whitespace-nowrap text-xs text-slate-500">min · {fmtDuration(Number(minutes) * 60 || 0)}</span>
          {changed && <Button size="sm" loading={update.isPending} onClick={() => update.mutate({ id: p.id, target_minutes: Number(minutes) })}>Save</Button>}
        </div>
      </td>
      <td>
        {p.category ? (
          <button className="text-xs" onClick={() => update.mutate({ id: p.id, is_active: !p.is_active })} disabled={update.isPending}>
            <Badge tone={p.is_active ? "green" : "slate"}>{p.is_active ? "Active" : "Inactive"}</Badge>
          </button>
        ) : <Badge tone="green" title="A priority's default can't be switched off">Active</Badge>}
      </td>
      <td className="text-right">
        {p.category && (
          <Button size="sm" variant="ghost" aria-label={`Delete ${p.name}`} icon={<Trash2 className="h-3.5 w-3.5" />} loading={remove.isPending}
            onClick={() => remove.mutate(p.id)} />
        )}
      </td>
    </tr>
  );
}

function CreatePolicy({ onClose }: { onClose: () => void }) {
  const categories = useCategories();
  const create = useCreateSlaPolicy();
  const [form, setForm] = useState({ name: "", priority: "High" as Priority, category: "", target_minutes: "240" });
  const [local, setLocal] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (form.name.trim().length < 3) return setLocal("Give the policy a name.");
    if (!(Number(form.target_minutes) >= 1)) return setLocal("The target must be at least 1 minute.");
    setLocal(null);
    create.mutate(
      { name: form.name.trim(), priority: form.priority, category: form.category || null, target_minutes: Number(form.target_minutes), is_active: true },
      { onSuccess: onClose },
    );
  }

  return (
    <Modal open title="New SLA policy" onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="sla-form" loading={create.isPending} icon={<Timer className="h-4 w-4" />}>Create policy</Button></>}>
      <form id="sla-form" onSubmit={submit} noValidate className="space-y-3">
        {(local || create.error) && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">{local ?? create.error?.message}</p>}
        <Field label="Name" htmlFor="sla-name"><Input id="sla-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Priority" htmlFor="sla-priority">
          <Select id="sla-priority" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as Priority })}>
            {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
          </Select>
        </Field>
        <Field label="Category" htmlFor="sla-category" hint="Leave empty for every category (the priority's default already exists).">
          <Select id="sla-category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
            <option value="">Every category</option>
            {categories.data?.map((c) => <option key={c.name}>{c.name}</option>)}
          </Select>
        </Field>
        <Field label="Target (minutes)" htmlFor="sla-target">
          <Input id="sla-target" type="number" min={1} value={form.target_minutes} onChange={(e) => setForm({ ...form, target_minutes: e.target.value })} />
        </Field>
      </form>
    </Modal>
  );
}
