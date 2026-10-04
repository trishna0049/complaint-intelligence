import { Pencil, Plus, Trash2, Users } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "@/api/http";
import { useCreateTeam, useDeleteTeam, useDepartments, useTeams, useUpdateTeam } from "@/api/client";
import type { Department, TeamInfo } from "@/api/types";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Select, Skeleton, Textarea } from "@/components/ui";

export function TeamsPage() {
  const teams = useTeams();
  const departments = useDepartments();
  const [editing, setEditing] = useState<TeamInfo | "new" | null>(null);
  const [deleting, setDeleting] = useState<TeamInfo | null>(null);

  const byDept = new Map<string, TeamInfo[]>();
  for (const t of teams.data ?? []) byDept.set(t.department.name, [...(byDept.get(t.department.name) ?? []), t]);

  return (
    <>
      <PageHeader
        title="Teams"
        description="Teams own complaint categories; the routing rules send each ticket to the team that owns its category."
        actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setEditing("new")} disabled={!departments.data}>New team</Button>}
      />
      {teams.error ? (
        <Card><ErrorState error={teams.error} onRetry={() => void teams.refetch()} /></Card>
      ) : teams.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-32" />)}</div>
      ) : (teams.data ?? []).length === 0 ? (
        <Card><EmptyState title="No teams yet" description="Run the seed script or create a team." /></Card>
      ) : (
        <div className="space-y-6">
          {[...byDept.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([dept, list]) => (
            <section key={dept}>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{dept}</h2>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {list.map((t) => (
                  <Card key={t.id}>
                    <CardHeader
                      title={t.name}
                      subtitle={t.description ?? undefined}
                      actions={<>
                        <Button variant="ghost" size="sm" aria-label={`Edit ${t.name}`} icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(t)} />
                        <Button variant="ghost" size="sm" aria-label={`Delete ${t.name}`} icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setDeleting(t)} />
                      </>}
                    />
                    <div className="space-y-2 px-4 py-3 text-sm">
                      <Link to={`/admin/users?team_id=${t.id}`} className="inline-flex items-center gap-1.5 text-brand-700 hover:underline">
                        <Users className="h-4 w-4" /> {t.member_count.toLocaleString()} active members
                      </Link>
                      <div className="flex flex-wrap gap-1.5">
                        {t.categories.length ? t.categories.map((c) => <Badge key={c} tone="blue">{c}</Badge>)
                          : <span className="text-xs text-slate-400">Owns no categories</span>}
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
      {editing && departments.data && (
        <TeamModal team={editing === "new" ? null : editing} departments={departments.data} onClose={() => setEditing(null)} />
      )}
      {deleting && <DeleteTeamModal team={deleting} onClose={() => setDeleting(null)} />}
    </>
  );
}

function TeamModal({ team, departments, onClose }: { team: TeamInfo | null; departments: Department[]; onClose: () => void }) {
  const create = useCreateTeam();
  const update = useUpdateTeam();
  const [form, setForm] = useState({
    name: team?.name ?? "", department_id: String(team?.department.id ?? departments[0]?.id ?? ""), description: team?.description ?? "",
  });
  const [local, setLocal] = useState<string | null>(null);
  const mutation = team ? update : create;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (form.name.trim().length < 2) return setLocal("Give the team a name.");
    setLocal(null);
    const body = { name: form.name.trim(), department_id: Number(form.department_id), description: form.description.trim() || null };
    if (team) update.mutate({ id: team.id, ...body }, { onSuccess: onClose });
    else create.mutate(body, { onSuccess: onClose });
  }

  return (
    <Modal open title={team ? `Edit ${team.name}` : "New team"} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="team-form" loading={mutation.isPending}>{team ? "Save changes" : "Create team"}</Button>
      </>}>
      <form id="team-form" onSubmit={submit} noValidate className="space-y-3">
        {(local || mutation.error) && (
          <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
            {local ?? (mutation.error instanceof ApiError ? mutation.error.message : "Something went wrong.")}
          </p>
        )}
        <Field label="Team name" htmlFor="t-name"><Input id="t-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} /></Field>
        <Field label="Department" htmlFor="t-dept">
          <Select id="t-dept" value={form.department_id} onChange={(e) => setForm((f) => ({ ...f, department_id: e.target.value }))}>
            {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
        </Field>
        <Field label="Description" htmlFor="t-desc">
          <Textarea id="t-desc" rows={3} value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
        </Field>
      </form>
    </Modal>
  );
}

function DeleteTeamModal({ team, onClose }: { team: TeamInfo; onClose: () => void }) {
  const del = useDeleteTeam();
  const blocked = team.member_count > 0 || team.categories.length > 0;
  return (
    <Modal open title={`Delete ${team.name}?`} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={blocked} loading={del.isPending} onClick={() => del.mutate(team.id, { onSuccess: onClose })}>Delete team</Button>
      </>}>
      {blocked ? (
        <p className="text-sm text-slate-700">
          This team still has {team.member_count} member{team.member_count === 1 ? "" : "s"} and {team.categories.length} categor
          {team.categories.length === 1 ? "y" : "ies"}. Move them to another team first.
        </p>
      ) : (
        <p className="text-sm text-slate-700">The team has no members or categories. This can't be undone.</p>
      )}
      {del.error && <p className="mt-2 text-sm text-rose-700" role="alert">{del.error.message}</p>}
    </Modal>
  );
}
