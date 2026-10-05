import { ArrowLeft, BookOpen, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "@/api/http";
import { useArticle, useArticles, useCategories, useCreateArticle, useDeleteArticle, useKnowledgeSearch, useUpdateArticle } from "@/api/client";
import type { Article, ArticleInput, ArticleSummary } from "@/api/types";
import { useAuth } from "@/auth/useAuth";
import { MatchBadge } from "@/components/ticket/Retrieval";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, LoadingState, Modal, PageHeader, Select, Skeleton, Textarea } from "@/components/ui";
import { fmtDateTime, fmtRelative } from "@/lib/format";

const GENERAL = "General";

/** Knowledge base: everyone reads and searches (by meaning and keywords); Admins create and edit. */
export function KnowledgePage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "ADMIN";
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  const categories = useCategories();
  const list = useArticles(category || undefined);
  const search = useKnowledgeSearch(q, category || undefined);
  const searching = q.trim().length > 1;

  useEffect(() => {
    const id = window.setTimeout(() => setQ(text), 300);
    return () => window.clearTimeout(id);
  }, [text]);

  const grouped = new Map<string, ArticleSummary[]>();
  for (const a of list.data?.items ?? []) grouped.set(a.category ?? GENERAL, [...(grouped.get(a.category ?? GENERAL) ?? []), a]);

  return (
    <>
      <PageHeader
        title="Knowledge base"
        description="Help articles and policies. The AI copilot grounds its answers in them."
        actions={isAdmin ? <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>New article</Button> : undefined}
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <div className="relative min-w-[260px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
            <Input aria-label="Search the knowledge base" placeholder="Describe the problem, e.g. “refund not credited to my card”" className="pl-8"
              value={text} onChange={(e) => setText(e.target.value)} />
          </div>
          <Select aria-label="Category" className="w-52" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {categories.data?.map((c) => <option key={c.name}>{c.name}</option>)}
          </Select>
        </div>

        {searching ? (
          search.error ? <ErrorState error={search.error} onRetry={() => void search.refetch()} /> : search.isLoading || !search.data ? (
            <div className="space-y-2 p-4"><Skeleton className="h-14" /><Skeleton className="h-14" /></div>
          ) : search.data.length === 0 ? (
            <EmptyState title="No matching articles" description="Try describing the problem in other words." icon={<BookOpen className="h-6 w-6" />} />
          ) : (
            <ul className="divide-y divide-slate-100" aria-label="Search results">
              {search.data.map((a) => (
                <ArticleRow key={a.id} article={a} extra={<MatchBadge matchedBy={a.matched_by} similarity={a.similarity} />} />
              ))}
            </ul>
          )
        ) : list.error ? <ErrorState error={list.error} onRetry={() => void list.refetch()} /> : list.isLoading || !list.data ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>
        ) : list.data.items.length === 0 ? (
          <EmptyState title="No articles yet" description={isAdmin ? "Create the first one." : "An Admin hasn't added any articles in this category."} icon={<BookOpen className="h-6 w-6" />} />
        ) : (
          <div className="divide-y divide-slate-100">
            {[...grouped.entries()].map(([group, items]) => (
              <section key={group} aria-label={group}>
                <h3 className="bg-slate-50/70 px-4 py-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">{group}</h3>
                <ul className="divide-y divide-slate-100">{items.map((a) => <ArticleRow key={a.id} article={a} />)}</ul>
              </section>
            ))}
          </div>
        )}
      </Card>
      {creating && <ArticleForm onClose={() => setCreating(false)} onSaved={(a) => navigate(`/knowledge/${a.id}`)} />}
    </>
  );
}

function ArticleRow({ article: a, extra }: { article: ArticleSummary; extra?: React.ReactNode }) {
  return (
    <li>
      <Link to={`/knowledge/${a.id}`} className="block px-4 py-3 hover:bg-slate-50">
        <div className="flex items-start justify-between gap-3">
          <span className="text-sm font-medium text-slate-900">{a.title}</span>
          {extra}
        </div>
        <p className="mt-0.5 line-clamp-2 text-xs text-slate-600">{a.snippet}</p>
        <p className="mt-1 text-[11px] text-slate-400">
          {a.category ?? GENERAL} · updated {fmtRelative(a.updated_at)}{a.usage_count > 0 && ` · cited by the copilot ${a.usage_count}×`}
        </p>
      </Link>
    </li>
  );
}

export function ArticlePage() {
  const id = Number(useParams().id);
  const { user } = useAuth();
  const isAdmin = user?.role === "ADMIN";
  const navigate = useNavigate();
  const { data: a, isLoading, error, refetch } = useArticle(id);
  const remove = useDeleteArticle(id);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  if (isLoading) return <LoadingState label="Loading article…" />;
  if (error || !a) {
    return (
      <Card>
        {error instanceof ApiError && error.status === 404 ? (
          <EmptyState title="Article not found" action={<Link to="/knowledge" className="text-sm text-brand-600 hover:underline">Back to the knowledge base</Link>} />
        ) : <ErrorState error={error} onRetry={() => void refetch()} />}
      </Card>
    );
  }
  return (
    <div className="max-w-3xl">
      <Link to="/knowledge" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> Knowledge base
      </Link>
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div>
            <Badge tone="slate">{a.category ?? GENERAL}</Badge>
            <h1 className="mt-1.5 text-xl font-semibold tracking-tight text-slate-900">{a.title}</h1>
            <p className="mt-0.5 text-xs text-slate-500">
              Updated {fmtDateTime(a.updated_at)}{a.updated_by && ` by ${a.updated_by.name}`} · cited by the copilot {a.usage_count}×
            </p>
          </div>
          {isAdmin && (
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(true)}>Edit</Button>
              {confirmDelete ? (
                <>
                  <Button size="sm" variant="danger" loading={remove.isPending} onClick={() => remove.mutate(undefined, { onSuccess: () => navigate("/knowledge") })}>
                    Delete for good
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>Keep</Button>
                </>
              ) : (
                <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setConfirmDelete(true)}>Delete</Button>
              )}
            </div>
          )}
        </div>
        <article className="space-y-3 px-5 py-4 text-sm leading-relaxed text-slate-800">
          {a.body.split(/\n{2,}/).map((p, i) => <p key={i} className="whitespace-pre-wrap">{p}</p>)}
        </article>
        {remove.isError && <p className="px-5 pb-4 text-sm text-rose-700" role="alert">{remove.error.message}</p>}
      </Card>
      {editing && <ArticleForm article={a} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />}
    </div>
  );
}

function ArticleForm({ article, onClose, onSaved }: { article?: Article; onClose: () => void; onSaved: (a: Article) => void }) {
  const categories = useCategories();
  const create = useCreateArticle();
  const update = useUpdateArticle(article?.id ?? 0);
  const mutation = article ? update : create;
  const [form, setForm] = useState<ArticleInput>({ title: article?.title ?? "", body: article?.body ?? "", category: article?.category ?? null });
  const [local, setLocal] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (form.title.trim().length < 3) return setLocal("Give the article a title (at least 3 characters).");
    if (form.body.trim().length < 20) return setLocal("Write at least 20 characters.");
    setLocal(null);
    const done = { onSuccess: (a: Article | undefined) => a && onSaved(a) };
    if (article) update.mutate(form, done);
    else create.mutate(form, done);
  }

  return (
    <Modal open wide title={article ? "Edit article" : "New article"} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="article-form" loading={mutation.isPending}>{article ? "Save changes" : "Create article"}</Button>
      </>}>
      <form id="article-form" onSubmit={submit} noValidate className="space-y-3">
        {(local || mutation.error) && (
          <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">{local ?? mutation.error?.message}</p>
        )}
        <Field label="Title" htmlFor="article-title">
          <Input id="article-title" value={form.title} maxLength={200} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field label="Category" htmlFor="article-category" hint="Articles of a ticket's category rank a little higher for that ticket.">
          <Select id="article-category" value={form.category ?? ""} onChange={(e) => setForm({ ...form, category: e.target.value || null })}>
            <option value="">General (all categories)</option>
            {categories.data?.map((c) => <option key={c.name}>{c.name}</option>)}
          </Select>
        </Field>
        <Field label="Article" htmlFor="article-body" hint="Blank lines separate paragraphs. Saving re-indexes the article for search.">
          <Textarea id="article-body" rows={12} value={form.body} maxLength={20_000} onChange={(e) => setForm({ ...form, body: e.target.value })} />
        </Field>
      </form>
    </Modal>
  );
}
