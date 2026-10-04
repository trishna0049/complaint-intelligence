import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError } from "@/api/http";
import { useCategories, useCreateCategory, useDeleteCategory, useTeams, useUpdateCategory } from "@/api/client";
import type { CategoryInfo, TeamInfo } from "@/api/types";
import { PriorityBadge } from "@/components/Badges";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Select, Skeleton, Textarea } from "@/components/ui";

export function CategoriesPage() {
  const categories = useCategories();
  const teams = useTeams();
  const [editing, setEditing] = useState<CategoryInfo | "new" | null>(null);
  const [deleting, setDeleting] = useState<CategoryInfo | null>(null);

  return (
    <>
      <PageHeader
        title="Categories"
        description="Complaint categories, the team that owns each one (routing) and its base priority (documented business rules)."
        actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setEditing("new")}>New category</Button>}
      />
      <Card>
        {categories.error ? (
          <ErrorState error={categories.error} onRetry={() => void categories.refetch()} />
        ) : categories.isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : (categories.data ?? []).length === 0 ? (
          <EmptyState title="No categories" description="Run the seed script or create a category." />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead><tr><th>Category</th><th>Owning team</th><th>Base priority</th><th /></tr></thead>
              <tbody>
                {categories.data!.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <p className="flex items-center gap-1.5 font-medium text-slate-900">
                        {c.name}
                        {c.builtin && <Badge tone="slate" title="Used by the classifier and the priority rules">Built-in</Badge>}
                      </p>
                      {c.description && <p className="text-xs text-slate-500">{c.description}</p>}
                    </td>
                    <td className="text-slate-700">{c.team?.name ?? <span className="text-amber-700">Unassigned — tickets go to the review queue</span>}</td>
                    <td><PriorityBadge priority={c.base_priority} /></td>
                    <td className="whitespace-nowrap text-right">
                      <Button variant="ghost" size="sm" aria-label={`Edit ${c.name}`} icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(c)} />
                      <Button variant="ghost" size="sm" aria-label={`Delete ${c.name}`} icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setDeleting(c)}
                        disabled={c.builtin} title={c.builtin ? "Built-in categories can't be deleted" : undefined} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {editing && <CategoryModal category={editing === "new" ? null : editing} teams={teams.data ?? []} onClose={() => setEditing(null)} />}
      {deleting && <DeleteCategoryModal category={deleting} onClose={() => setDeleting(null)} />}
    </>
  );
}

function CategoryModal({ category, teams, onClose }: { category: CategoryInfo | null; teams: TeamInfo[]; onClose: () => void }) {
  const create = useCreateCategory();
  const update = useUpdateCategory();
  const mutation = category ? update : create;
  const [form, setForm] = useState({ name: category?.name ?? "", description: category?.description ?? "", team_id: String(category?.team?.id ?? "") });
  const [local, setLocal] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (form.name.trim().length < 2) return setLocal("Give the category a name.");
    setLocal(null);
    const teamId = form.team_id ? Number(form.team_id) : null;
    if (category) {
      update.mutate(
        { id: category.id, name: category.builtin ? undefined : form.name.trim(), description: form.description.trim() || null,
          ...(teamId === null ? { clear_team: true } : { team_id: teamId }) },
        { onSuccess: onClose },
      );
    } else {
      create.mutate({ name: form.name.trim(), description: form.description.trim() || null, team_id: teamId }, { onSuccess: onClose });
    }
  }

  return (
    <Modal open title={category ? `Edit ${category.name}` : "New category"} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="cat-form" loading={mutation.isPending}>{category ? "Save changes" : "Create category"}</Button>
      </>}>
      <form id="cat-form" onSubmit={submit} noValidate className="space-y-3">
        {(local || mutation.error) && (
          <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
            {local ?? (mutation.error instanceof ApiError ? mutation.error.message : "Something went wrong.")}
          </p>
        )}
        <Field label="Name" htmlFor="c-name" hint={category?.builtin ? "Built-in: the classifier and the priority rules use this name." : undefined}>
          <Input id="c-name" value={form.name} disabled={category?.builtin} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        </Field>
        <Field label="Owning team" htmlFor="c-team" hint="New tickets in this category are routed to this team.">
          <Select id="c-team" value={form.team_id} onChange={(e) => setForm((f) => ({ ...f, team_id: e.target.value }))}>
            <option value="">Unassigned</option>
            {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </Select>
        </Field>
        <Field label="Description" htmlFor="c-desc">
          <Textarea id="c-desc" rows={2} value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
        </Field>
      </form>
    </Modal>
  );
}

function DeleteCategoryModal({ category, onClose }: { category: CategoryInfo; onClose: () => void }) {
  const del = useDeleteCategory();
  return (
    <Modal open title={`Delete ${category.name}?`} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="danger" loading={del.isPending} onClick={() => del.mutate(category.id, { onSuccess: onClose })}>Delete category</Button>
      </>}>
      <p className="text-sm text-slate-700">
        Existing tickets keep their category label; new tickets can no longer be filed under it. This can't be undone.
      </p>
      {del.error && <p className="mt-2 text-sm text-rose-700" role="alert">{del.error.message}</p>}
    </Modal>
  );
}
