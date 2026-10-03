import { ChevronLeft, ChevronRight, FileText, Plus, Search, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useCategories, useComplaints } from "@/api/client";
import { PriorityBadge, SentimentBadge, StatusBadge } from "@/components/Badges";
import { SENTIMENTS } from "@/lib/colors";
import { Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, Select, Skeleton } from "@/components/ui";
import { fmtRelative } from "@/lib/format";

const FILTERS = ["q", "status", "category", "sentiment", "priority", "channel", "source", "needs_review", "sort"] as const;

export function ComplaintsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const categories = useCategories();
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
  const { data, isLoading, error, refetch, isFetching } = useComplaints(query);
  const hasFilters = FILTERS.some((k) => params.get(k));
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const select = (key: string, label: string, options: string[], width = "w-40") => (
    <Select aria-label={label} className={width} value={params.get(key) ?? ""} onChange={(e) => update({ [key]: e.target.value || null })}>
      <option value="">{label}</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </Select>
  );

  return (
    <>
      <PageHeader
        title="Complaints"
        description="Every complaint with its AI triage. Click a row for the AI summary and recommended actions."
        actions={<Link to="/complaints/new"><Button icon={<Plus className="h-4 w-4" />}>New complaint</Button></Link>}
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
            <Input aria-label="Search complaints" placeholder="Search text, CMP-reference or order id…" className="pl-8"
              value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          {select("status", "Any status", ["Open", "In Progress", "Resolved"], "w-36")}
          {select("category", "Any category", categories.data?.map((c) => c.name) ?? [], "w-44")}
          {select("sentiment", "Any sentiment", [...SENTIMENTS], "w-40")}
          {select("priority", "Any priority", ["Critical", "High", "Medium", "Low"], "w-36")}
          {select("source", "All sources", ["new", "dataset"], "w-36")}
          <Select aria-label="Sort" className="w-44" value={params.get("sort") ?? "newest"} onChange={(e) => update({ sort: e.target.value === "newest" ? null : e.target.value })}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="priority">Highest priority</option>
          </Select>
          <label className="flex items-center gap-1.5 text-sm text-slate-600">
            <input type="checkbox" className="rounded border-slate-300" checked={params.get("needs_review") === "true"}
              onChange={(e) => update({ needs_review: e.target.checked ? "true" : null })} />
            Needs review
          </label>
          {hasFilters && (
            <Button variant="ghost" size="sm" icon={<X className="h-3.5 w-3.5" />}
              onClick={() => { setSearch(""); setParams(new URLSearchParams(), { replace: true }); }}>
              Clear
            </Button>
          )}
        </div>

        {error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <div className="space-y-2 p-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : data.items.length === 0 ? (
          <EmptyState title="No complaints match" description={hasFilters ? "Try clearing some filters." : "Import the dataset or log a complaint."} />
        ) : (
          <div className={isFetching ? "opacity-70 transition-opacity" : ""}>
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Reference</th><th>Complaint</th><th>Category / intent</th><th>Sentiment</th><th>Priority</th><th>Status</th><th className="text-right">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((c) => (
                    <tr key={c.id} tabIndex={0} className="cursor-pointer hover:bg-slate-50"
                      onClick={() => navigate(`/complaints/${c.id}`)} onKeyDown={(e) => e.key === "Enter" && navigate(`/complaints/${c.id}`)}>
                      <td className="whitespace-nowrap font-mono text-xs text-slate-500">{c.reference}</td>
                      <td className="max-w-[360px]">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate font-medium text-slate-900">{c.subject}</span>
                          {c.text_is_template && <span title="Source row had no customer text"><FileText className="h-3.5 w-3.5 shrink-0 text-slate-300" /></span>}
                          {c.needs_review && <Badge tone="violet" className="shrink-0"><Sparkles className="h-3 w-3" />Review</Badge>}
                        </div>
                        <p className="text-xs text-slate-500">{c.channel}{c.customer_name ? ` · ${c.customer_name}` : ""}{c.source === "dataset" ? " · historical" : ""}</p>
                      </td>
                      <td className="max-w-[200px]">
                        <p className="truncate text-slate-700">{c.category ?? "—"}</p>
                        <p className="truncate text-xs text-slate-500">{c.intent}</p>
                      </td>
                      <td><SentimentBadge sentiment={c.sentiment} /></td>
                      <td><PriorityBadge priority={c.priority} /></td>
                      <td><StatusBadge status={c.status} /></td>
                      <td className="whitespace-nowrap text-right text-xs text-slate-500">{fmtRelative(c.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500">
              <span>{data.total.toLocaleString()} complaints</span>
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
