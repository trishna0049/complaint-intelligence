import { ChevronLeft, ChevronRight, Pencil, Plus, Search, UserPlus, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/http";
import { useCreateUser, useTeams, useUpdateUser, useUsers } from "@/api/client";
import type { Role, TeamInfo, User } from "@/api/types";
import { useAuth } from "@/auth/useAuth";
import { Avatar, Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Select, Skeleton } from "@/components/ui";
import { fmtRelative } from "@/lib/format";

const FILTERS = ["q", "role", "team_id", "active"] as const;

export function UsersPage() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const teams = useTeams();
  const page = Number(params.get("page") ?? 1);

  function update(next: Record<string, string | null>, resetPage = true) {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v) p.set(k, v);
      else p.delete(k);
    }
    if (resetPage) p.delete("page");
    setParams(p, { replace: true });
  }

  useEffect(() => {
    const id = window.setTimeout(() => {
      if ((params.get("q") ?? "") !== search) update({ q: search || null });
    }, 350);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const query = useMemo(() => {
    const q: Record<string, string | number> = { page, page_size: 25 };
    for (const k of FILTERS) {
      const v = params.get(k);
      if (v) q[k] = v;
    }
    return q;
  }, [params, page]);
  const { data, isLoading, error, refetch, isFetching } = useUsers(query);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const hasFilters = FILTERS.some((k) => params.get(k));

  return (
    <>
      <PageHeader
        title="Users"
        description="Admins and agents. Agents imported from the dataset keep their supervisor; deactivated users can't sign in."
        actions={<Button icon={<UserPlus className="h-4 w-4" />} onClick={() => setCreating(true)}>New user</Button>}
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
            <Input aria-label="Search users" placeholder="Search name or email…" className="pl-8" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <Select aria-label="Role" className="w-36" value={params.get("role") ?? ""} onChange={(e) => update({ role: e.target.value || null })}>
            <option value="">Any role</option>
            <option value="ADMIN">Admin</option>
            <option value="AGENT">Agent</option>
          </Select>
          <Select aria-label="Team" className="w-52" value={params.get("team_id") ?? ""} onChange={(e) => update({ team_id: e.target.value || null })}>
            <option value="">Any team</option>
            {teams.data?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </Select>
          <Select aria-label="Status" className="w-36" value={params.get("active") ?? ""} onChange={(e) => update({ active: e.target.value || null })}>
            <option value="">Any status</option>
            <option value="true">Active</option>
            <option value="false">Deactivated</option>
          </Select>
          {hasFilters && (
            <Button variant="ghost" size="sm" icon={<X className="h-3.5 w-3.5" />} onClick={() => { setSearch(""); setParams(new URLSearchParams(), { replace: true }); }}>
              Clear
            </Button>
          )}
        </div>
        {error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <div className="space-y-2 p-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : data.items.length === 0 ? (
          <EmptyState title="No users match" description={hasFilters ? "Try clearing some filters." : "Create the first user."} />
        ) : (
          <div className={isFetching ? "opacity-70 transition-opacity" : ""}>
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr><th>User</th><th>Role</th><th>Team</th><th>Supervisor</th><th>Status</th><th>Last sign-in</th><th /></tr>
                </thead>
                <tbody>
                  {data.items.map((u) => (
                    <tr key={u.id}>
                      <td>
                        <div className="flex items-center gap-2.5">
                          <Avatar name={u.name} size="sm" />
                          <div className="min-w-0">
                            <p className="truncate font-medium text-slate-900">{u.name}</p>
                            <p className="truncate text-xs text-slate-500">{u.email}</p>
                          </div>
                        </div>
                      </td>
                      <td><Badge tone={u.role === "ADMIN" ? "violet" : "slate"}>{u.role === "ADMIN" ? "Admin" : "Agent"}</Badge></td>
                      <td className="text-slate-700">{u.team?.name ?? <span className="text-slate-400">—</span>}</td>
                      <td className="text-xs text-slate-500">{u.supervisor ?? "—"}</td>
                      <td>{u.is_active ? <Badge tone="green" dot>Active</Badge> : <Badge tone="slate" dot>Deactivated</Badge>}</td>
                      <td className="whitespace-nowrap text-xs text-slate-500">{u.last_login_at ? fmtRelative(u.last_login_at) : "Never"}</td>
                      <td className="text-right">
                        <Button variant="ghost" size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(u)} aria-label={`Edit ${u.name}`}>
                          Edit
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500">
              <span>{data.total.toLocaleString()} users</span>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="sm" aria-label="Previous page" disabled={page <= 1} onClick={() => update({ page: String(page - 1) }, false)}>
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="tabular-nums">Page {page} / {pages.toLocaleString()}</span>
                <Button variant="ghost" size="sm" aria-label="Next page" disabled={page >= pages} onClick={() => update({ page: String(page + 1) }, false)}>
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </Card>
      {creating && <CreateUserModal teams={teams.data ?? []} onClose={() => setCreating(false)} />}
      {editing && <EditUserModal user={editing} teams={teams.data ?? []} onClose={() => setEditing(null)} />}
    </>
  );
}

function errorText(err: unknown): string | null {
  if (!err) return null;
  return err instanceof ApiError ? err.message : "Something went wrong.";
}

function CreateUserModal({ teams, onClose }: { teams: TeamInfo[]; onClose: () => void }) {
  const create = useCreateUser();
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "AGENT" as Role, team_id: "" });
  const [local, setLocal] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function submit(e: FormEvent) {
    e.preventDefault();
    if (form.name.trim().length < 2 || !form.email.includes("@")) return setLocal("Enter a name and a valid email.");
    if (form.password.length < 10) return setLocal("The password needs at least 10 characters with letters and digits.");
    setLocal(null);
    create.mutate(
      { name: form.name.trim(), email: form.email.trim(), password: form.password, role: form.role, team_id: form.team_id ? Number(form.team_id) : null },
      { onSuccess: onClose },
    );
  }

  return (
    <Modal open title="New user" onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="create-user" loading={create.isPending} icon={<Plus className="h-4 w-4" />}>Create user</Button>
      </>}>
      <form id="create-user" onSubmit={submit} noValidate className="space-y-3">
        {(local || create.error) && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">{local ?? errorText(create.error)}</p>}
        <Field label="Full name" htmlFor="u-name"><Input id="u-name" value={form.name} onChange={set("name")} /></Field>
        <Field label="Email" htmlFor="u-email"><Input id="u-email" type="email" value={form.email} onChange={set("email")} /></Field>
        <Field label="Initial password" htmlFor="u-pw" hint="At least 10 characters with letters and digits. Share it securely.">
          <Input id="u-pw" type="password" autoComplete="new-password" value={form.password} onChange={set("password")} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Role" htmlFor="u-role">
            <Select id="u-role" value={form.role} onChange={set("role")}>
              <option value="AGENT">Agent</option>
              <option value="ADMIN">Admin</option>
            </Select>
          </Field>
          <Field label="Team" htmlFor="u-team">
            <Select id="u-team" value={form.team_id} onChange={set("team_id")}>
              <option value="">No team</option>
              {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </Select>
          </Field>
        </div>
      </form>
    </Modal>
  );
}

function EditUserModal({ user, teams, onClose }: { user: User; teams: TeamInfo[]; onClose: () => void }) {
  const { user: me } = useAuth();
  const update = useUpdateUser();
  const [form, setForm] = useState({
    name: user.name, role: user.role, team_id: user.team ? String(user.team.id) : "", active: user.is_active, password: "",
  });
  const [local, setLocal] = useState<string | null>(null);
  const isSelf = me?.id === user.id;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (form.password && form.password.length < 10) return setLocal("The new password needs at least 10 characters.");
    setLocal(null);
    const teamId = form.team_id ? Number(form.team_id) : null;
    update.mutate(
      {
        id: user.id,
        name: form.name.trim() !== user.name ? form.name.trim() : undefined,
        role: form.role !== user.role ? form.role : undefined,
        ...(teamId === (user.team?.id ?? null) ? {} : teamId === null ? { clear_team: true } : { team_id: teamId }),
        is_active: form.active !== user.is_active ? form.active : undefined,
        password: form.password || undefined,
      },
      { onSuccess: onClose },
    );
  }

  return (
    <Modal open title={`Edit ${user.name}`} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="edit-user" loading={update.isPending}>Save changes</Button>
      </>}>
      <form id="edit-user" onSubmit={submit} noValidate className="space-y-3">
        {(local || update.error) && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">{local ?? errorText(update.error)}</p>}
        <p className="text-xs text-slate-500">{user.email}{user.source === "dataset" ? " · imported from the dataset" : ""}</p>
        <Field label="Full name" htmlFor="e-name"><Input id="e-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Role" htmlFor="e-role">
            <Select id="e-role" value={form.role} disabled={isSelf} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as Role }))}>
              <option value="AGENT">Agent</option>
              <option value="ADMIN">Admin</option>
            </Select>
          </Field>
          <Field label="Team" htmlFor="e-team">
            <Select id="e-team" value={form.team_id} onChange={(e) => setForm((f) => ({ ...f, team_id: e.target.value }))}>
              <option value="">No team</option>
              {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </Select>
          </Field>
        </div>
        <Field label="Reset password (optional)" htmlFor="e-pw" hint="Changing the role, the password or deactivating signs the user out everywhere.">
          <Input id="e-pw" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
        </Field>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" className="rounded border-slate-300" checked={form.active} disabled={isSelf}
            onChange={(e) => setForm((f) => ({ ...f, active: e.target.checked }))} />
          Active (can sign in)
        </label>
        {isSelf && <p className="text-xs text-slate-500">You can't change your own role or deactivate yourself.</p>}
      </form>
    </Modal>
  );
}
