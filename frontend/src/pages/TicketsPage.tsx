import clsx from "clsx";
import { ChevronLeft, ChevronRight, FileText, Plus, Search, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useCategories, useTeams, useTickets } from "@/api/client";
import { PriorityBadge, SentimentBadge, StatusBadge } from "@/components/Badges";
import { Avatar, Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, Select, Skeleton } from "@/components/ui";
import { useAuth } from "@/auth/useAuth";
import { SENTIMENTS } from "@/lib/colors";
import { fmtRelative } from "@/lib/format";

/** Saved queue views: each one is a fixed set of API filters. */
const VIEWS = [
  { id: "open", label: "All open", query: { status: "open" } },
  { id: "unassigned", label: "Unassigned", query: { status: "open", assignee: "none" } },
  { id: "mine", label: "Assigned to me", query: { status: "open", assignee: "me" } },
  { id: "escalated", label: "Escalated", query: { status: "ESCALATED" } },
  { id: "review", label: "Needs review", query: { status: "open", needs_review: "true" } },
  { id: "done", label: "Resolved & closed", query: { status: "RESOLVED,CLOSED" } },
  { id: "all", label: "All tickets", query: {} },
] as const;

const FILTERS = ["q", "category", "sentiment", "priority", "team_id", "source", "sort"] as const;

export function TicketsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "ADMIN";
  const [search, setSearch] = useState(params.get("q") ?? "");
  const categories = useCategories();
  const teams = useTeams();
  const page = Number(params.get("page") ?? 1);
  // Old links used ?status=...; they still work as a plain filter on top of the "all" view.
  const legacyStatus = params.get("status");
  const viewId = params.get("view") ?? (legacyStatus ? "all" : "open");
  const view = VIEWS.find((v) => v.id === viewId) ?? VIEWS[0];

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
    const q: Record<string, string | number> = { page, page_size: 25, ...view.query };
    if (legacyStatus) q.status = legacyStatus;
    for (const k of FILTERS) {
      const v = params.get(k);
      if (v) q[k] = v;
    }
    return q;
  }, [params, page, view, legacyStatus]);
  const { data, isLoading, error, refetch, isFetching } = useTickets(query);
  const hasFilters = FILTERS.some((k) => k !== "sort" && params.get(k));
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const select = (key: string, label: string, options: { value: string; label: string }[], width = "w-40") => (
    <Select aria-label={label} className={width} value={params.get(key) ?? ""} onChange={(e) => update({ [key]: e.target.value || null })}>
      <option value="">{label}</option>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </Select>
  );

  return (
    <>
      <PageHeader
        title="Ticket queue"
        description={isAdmin ? "Every ticket across all teams." : `Tickets for you and ${user?.team?.name ?? "your team"}, plus tickets you created.`}
        actions={<Link to="/tickets/new"><Button icon={<Plus className="h-4 w-4" />}>Create ticket</Button></Link>}
      />
      <Card>
        <div className="flex gap-1 overflow-x-auto border-b border-slate-100 px-3 pt-2" role="tablist" aria-label="Queue views">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              role="tab"
              aria-selected={v.id === view.id}
              onClick={() => update({ view: v.id === "open" ? null : v.id, status: null })}
              className={clsx(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                v.id === view.id ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800",
              )}
            >
              {v.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
            <Input aria-label="Search tickets" placeholder="Search text, INC- number or order id…" className="pl-8"
              value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          {select("priority", "Any priority", ["Critical", "High", "Medium", "Low"].map((p) => ({ value: p, label: p })), "w-36")}
          {select("category", "Any category", categories.data?.map((c) => ({ value: c.name, label: c.name })) ?? [], "w-44")}
          {select("sentiment", "Any sentiment", SENTIMENTS.map((s) => ({ value: s, label: s })), "w-40")}
          {isAdmin && select("team_id", "Any team", teams.data?.map((t) => ({ value: String(t.id), label: t.name })) ?? [], "w-48")}
          {select("source", "All sources", [{ value: "new", label: "Created in app" }, { value: "dataset", label: "Historical" }], "w-40")}
          <Select aria-label="Sort" className="w-44" value={params.get("sort") ?? "newest"} onChange={(e) => update({ sort: e.target.value === "newest" ? null : e.target.value })}>
            <option value="newest">Newest first</option>
            <option value="updated">Recently updated</option>
            <option value="priority">Highest priority</option>
            <option value="oldest">Oldest first</option>
          </Select>
          {(hasFilters || legacyStatus) && (
            <Button variant="ghost" size="sm" icon={<X className="h-3.5 w-3.5" />}
              onClick={() => { setSearch(""); setParams(new URLSearchParams(view.id === "open" ? {} : { view: view.id }), { replace: true }); }}>
              Clear
            </Button>
          )}
        </div>

        {error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <div className="space-y-2 p-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : data.items.length === 0 ? (
          <EmptyState title="No tickets match" description={hasFilters ? "Try clearing some filters." : `Nothing in “${view.label}” right now.`} />
        ) : (
          <div className={isFetching ? "opacity-70 transition-opacity" : ""}>
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Ticket</th><th>Subject</th><th>Category / intent</th><th>Sentiment</th><th>Priority</th><th>Status</th><th>Assignee</th>
                    <th className="text-right">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((t) => (
                    <tr key={t.id} tabIndex={0} className="cursor-pointer hover:bg-slate-50"
                      onClick={() => navigate(`/tickets/${t.id}`)} onKeyDown={(e) => e.key === "Enter" && navigate(`/tickets/${t.id}`)}>
                      <td className="whitespace-nowrap font-mono text-xs text-slate-500">{t.ticket_number}</td>
                      <td className="max-w-[340px]">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate font-medium text-slate-900">{t.subject}</span>
                          {t.description_source === "template" && <span title="Source row had no customer text"><FileText className="h-3.5 w-3.5 shrink-0 text-slate-300" /></span>}
                          {t.needs_review && <Badge tone="violet" className="shrink-0"><Sparkles className="h-3 w-3" />Review</Badge>}
                        </div>
                        <p className="text-xs text-slate-500">{t.channel}{t.customer_name ? ` · ${t.customer_name}` : ""}{t.source === "dataset" ? " · historical" : ""}</p>
                      </td>
                      <td className="max-w-[190px]">
                        <p className="truncate text-slate-700">{t.category ?? "—"}</p>
                        <p className="truncate text-xs text-slate-500">{t.intent}</p>
                      </td>
                      <td><SentimentBadge sentiment={t.sentiment} /></td>
                      <td><PriorityBadge priority={t.priority} /></td>
                      <td><StatusBadge status={t.status} /></td>
                      <td className="max-w-[180px]">
                        {t.assignee ? (
                          <div className="flex items-center gap-1.5">
                            <Avatar name={t.assignee.name} size="sm" />
                            <span className="truncate text-slate-700">{t.assignee.name}</span>
                          </div>
                        ) : (
                          <span className="text-xs text-amber-700">Unassigned</span>
                        )}
                        {t.team && <p className="truncate pl-0.5 text-xs text-slate-500">{t.team.name}</p>}
                      </td>
                      <td className="whitespace-nowrap text-right text-xs text-slate-500">{fmtRelative(t.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500">
              <span>{data.total.toLocaleString()} tickets</span>
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
    </>
  );
}
