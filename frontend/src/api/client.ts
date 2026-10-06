import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  Analysis,
  AppNotification,
  NotificationPage,
  SlaAnalytics,
  SlaPolicy,
  DeadLetter,
  PipelineStatus,
  Article,
  ArticleHit,
  ArticleInput,
  ArticleSummary,
  Attachment,
  Comment,
  CategoryBreakdowns,
  CategoryInfo,
  Department,
  Emerging,
  Granularity,
  Overview,
  Page,
  Ticket,
  TicketDetail,
  TicketInput,
  Trends,
  TeamInfo,
  TeamMember,
  TicketSummary,
  TriagePreview,
  SimilarTicket,
  User,
  UserInput,
  UserPatch,
} from "./types";

import { api, type Query } from "./http";

export { ApiError, api } from "./http";

const keep = { placeholderData: keepPreviousData };

// ------------------------------------------------------------------ analytics
export const useOverview = (days: number) =>
  useQuery({ queryKey: ["analytics", "overview", days], queryFn: () => api<Overview>("/analytics/overview", { query: { days } }), ...keep });

export const useTrends = (days: number, granularity: Granularity) =>
  useQuery({ queryKey: ["analytics", "trends", days, granularity], queryFn: () => api<Trends>("/analytics/trends", { query: { days, granularity } }), ...keep });

export const useCategoryBreakdowns = (days: number) =>
  useQuery({ queryKey: ["analytics", "categories", days], queryFn: () => api<CategoryBreakdowns>("/analytics/categories", { query: { days } }), ...keep });

export const useEmerging = () =>
  useQuery({ queryKey: ["analytics", "emerging"], queryFn: () => api<Emerging>("/analytics/emerging") });

// ------------------------------------------------------------------ tickets
export const useTickets = (query: Query) =>
  useQuery({ queryKey: ["tickets", query], queryFn: () => api<Page<Ticket>>("/tickets", { query }), ...keep });

/** The SLA worker reacts to a change a moment later: the clock hasn't caught up with the ticket's state yet. */
function slaLagging(t: TicketDetail): boolean {
  const state = t.sla?.state ?? "none";
  const done = t.status === "RESOLVED" || t.status === "CLOSED";
  if (done) return state === "running" || state === "at_risk" || state === "paused";
  if (t.status === "WAITING_CUSTOMER") return state !== "paused" && state !== "breached" && state !== "none";
  if (t.status === "NEW") return false;
  return state === "none" || state === "paused" || state === "met";
}

/** While the AI worker triages, the LLM worker drafts or the SLA worker catches up, the ticket is refreshed every
 * 1.5 s (for a bounded time). */
export const useTicket = (id: number) =>
  useQuery({
    queryKey: ["ticket", id],
    queryFn: () => api<TicketDetail>(`/tickets/${id}`),
    enabled: Number.isFinite(id),
    refetchInterval: (query) => {
      const t = query.state.data;
      if (!t) return false;
      const working = t.pipeline?.triage === "pending" || t.pipeline?.copilot === "drafting";
      if (working && Date.now() - new Date(t.created_at).getTime() < 180_000) return 1500;
      return slaLagging(t) && Date.now() - new Date(t.updated_at).getTime() < 60_000 ? 1500 : false;
    },
  });

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: () => api<{ classifier: string | null; sentiment_model: string; llm_provider: string }>("/health"), staleTime: 60_000 });

export const useCategories = () =>
  useQuery({ queryKey: ["categories"], queryFn: () => api<CategoryInfo[]>("/categories"), staleTime: 5 * 60_000 });

export function useCreateTicket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TicketInput) => api<TicketDetail>("/tickets", { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tickets"] });
      void qc.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

export const useAnalyze = () =>
  useMutation({ mutationFn: (body: TicketInput) => api<TriagePreview>("/ai/analyze", { method: "POST", body }) });

/** Any change that returns the updated ticket: PATCH (status / category) and the lifecycle actions. */
function useTicketChange<TVars>(id: number, request: (vars: TVars) => Promise<TicketDetail>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (data) => {
      qc.setQueryData(["ticket", id], data);
      void qc.invalidateQueries({ queryKey: ["tickets"] });
      void qc.invalidateQueries({ queryKey: ["ticket-summary"] });
      void qc.invalidateQueries({ queryKey: ["analytics"] });
      void qc.invalidateQueries({ queryKey: ["team-members"] });
    },
  });
}

export const useUpdateTicket = (id: number) =>
  useTicketChange(id, (body: { status?: "IN_PROGRESS" | "WAITING_CUSTOMER"; category?: string }) =>
    api<TicketDetail>(`/tickets/${id}`, { method: "PATCH", body }));

export const useAssign = (id: number) =>
  useTicketChange(id, (body: { assignee_id: number; note?: string }) => api<TicketDetail>(`/tickets/${id}/assign`, { method: "POST", body }));

export const useAutoAssign = (id: number) =>
  useTicketChange(id, () => api<TicketDetail>(`/tickets/${id}/auto-assign`, { method: "POST" }));

export const useEscalate = (id: number) =>
  useTicketChange(id, (reason: string) => api<TicketDetail>(`/tickets/${id}/escalate`, { method: "POST", body: { reason } }));

export const useResolve = (id: number) =>
  useTicketChange(id, (resolution: string) => api<TicketDetail>(`/tickets/${id}/resolve`, { method: "POST", body: { resolution } }));

export const useClose = (id: number) => useTicketChange(id, () => api<TicketDetail>(`/tickets/${id}/close`, { method: "POST" }));

export const useReopen = (id: number) =>
  useTicketChange(id, (reason: string) => api<TicketDetail>(`/tickets/${id}/reopen`, { method: "POST", body: { reason } }));

export const useTicketSummary = (query: Query = {}) =>
  useQuery({ queryKey: ["ticket-summary", query], queryFn: () => api<TicketSummary>("/tickets/summary", { query }) });

export const useTeamMembers = (teamId: number | null | undefined) =>
  useQuery({
    queryKey: ["team-members", teamId],
    queryFn: () => api<TeamMember[]>(`/teams/${teamId}/members`),
    enabled: !!teamId,
  });

export function useAddComment(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => api<Comment>(`/tickets/${id}/comments`, { method: "POST", body: { body } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["ticket", id] }),
  });
}

export function useUploadAttachment(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<Attachment>(`/tickets/${id}/attachments`, { method: "POST", form });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["ticket", id] }),
  });
}

/** Attachments need the bearer token, so they are fetched with it and handed to the browser as a blob. */
export async function downloadAttachment(ticketId: number, att: Attachment) {
  const blob = await api<Blob>(`/tickets/${ticketId}/attachments/${att.id}`, { raw: true });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = att.filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Run (or re-run) the copilot. A previous pending draft becomes "superseded". */
export function useDraftResponse(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<Analysis>("/ai/draft-response", { method: "POST", body: { ticket_id: id } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["ticket", id] }),
  });
}

/** The agent approves the draft (as is or edited): it is posted as their AI-assisted comment. */
export const useAcceptDraft = (ticketId: number) =>
  useTicketChange(ticketId, ({ analysisId, response }: { analysisId: number; response: string }) =>
    api<TicketDetail>(`/ai/drafts/${analysisId}/accept`, { method: "POST", body: { response } }));

export const useDiscardDraft = (ticketId: number) =>
  useTicketChange(ticketId, ({ analysisId, reason }: { analysisId: number; reason?: string }) =>
    api<TicketDetail>(`/ai/drafts/${analysisId}/discard`, { method: "POST", body: { reason } }));

// ------------------------------------------------------------------ retrieval: similar tickets, knowledge base
/** `version` changes when the AI worker finishes (triage state + category), so results computed while the ticket
 * was still NEW — no category boost, no stored embedding — are fetched again. */
export const useSimilarTickets = (id: number, version = "") =>
  useQuery({ queryKey: ["similar", id, version], queryFn: () => api<SimilarTicket[]>(`/tickets/${id}/similar`), staleTime: 60_000 });

export const useTicketArticles = (id: number, version = "") =>
  useQuery({
    queryKey: ["ticket-articles", id, version],
    queryFn: () => api<ArticleHit[]>("/knowledge/search", { query: { ticket_id: id, limit: 3 } }),
    staleTime: 60_000,
  });

export const useKnowledgeSearch = (q: string, category?: string) =>
  useQuery({
    queryKey: ["knowledge-search", q, category],
    queryFn: () => api<ArticleHit[]>("/knowledge/search", { query: { q, category, limit: 10 } }),
    enabled: q.trim().length > 1,
    ...keep,
  });

export const useArticles = (category?: string) =>
  useQuery({
    queryKey: ["articles", category],
    queryFn: () => api<Page<ArticleSummary>>("/knowledge", { query: { category, page_size: 200 } }),
  });

export const useArticle = (id: number) => useQuery({ queryKey: ["article", id], queryFn: () => api<Article>(`/knowledge/${id}`) });

function useArticleChange<TVars>(request: (vars: TVars) => Promise<Article | undefined>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (data) => {
      if (data) qc.setQueryData(["article", data.id], data);
      for (const key of ["articles", "knowledge-search", "ticket-articles"]) void qc.invalidateQueries({ queryKey: [key] });
    },
  });
}

export const useCreateArticle = () => useArticleChange((body: ArticleInput) => api<Article>("/knowledge", { method: "POST", body }));
export const useUpdateArticle = (id: number) =>
  useArticleChange((body: Partial<ArticleInput>) => api<Article>(`/knowledge/${id}`, { method: "PATCH", body }));
export const useDeleteArticle = (id: number) =>
  useArticleChange(() => api<undefined>(`/knowledge/${id}`, { method: "DELETE" }));

// ------------------------------------------------------------------ notifications
export const useNotificationList = (unread: boolean, pageSize = 20) =>
  useQuery({
    queryKey: ["notifications", unread, pageSize],
    queryFn: () => api<NotificationPage>("/notifications", { query: { unread, page_size: pageSize } }),
  });

function useNotificationChange<TVars>(request: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: request, onSuccess: () => void qc.invalidateQueries({ queryKey: ["notifications"] }) });
}

export const useMarkNotificationRead = () =>
  useNotificationChange((id: number) => api<AppNotification>(`/notifications/${id}/read`, { method: "POST" }));
export const useMarkAllNotificationsRead = () =>
  useNotificationChange(() => api<{ marked: number }>("/notifications/read-all", { method: "POST" }));

export const useNotificationPreferences = () =>
  useQuery({ queryKey: ["notification-preferences"], queryFn: () => api<{ email: boolean }>("/notifications/preferences") });

export function useSetNotificationPreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (email: boolean) => api<{ email: boolean }>("/notifications/preferences", { method: "PUT", body: { email } }),
    onSuccess: (data) => qc.setQueryData(["notification-preferences"], data),
  });
}

// ------------------------------------------------------------------ SLA
export const useSlaPolicies = () => useQuery({ queryKey: ["sla-policies"], queryFn: () => api<SlaPolicy[]>("/sla-policies") });

function useSlaPolicyChange<TVars>(request: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: request, onSuccess: () => void qc.invalidateQueries({ queryKey: ["sla-policies"] }) });
}

export const useCreateSlaPolicy = () =>
  useSlaPolicyChange((body: Omit<SlaPolicy, "id" | "created_at" | "updated_at">) => api<SlaPolicy>("/sla-policies", { method: "POST", body }));
export const useUpdateSlaPolicy = () =>
  useSlaPolicyChange(({ id, ...body }: { id: number; name?: string; target_minutes?: number; is_active?: boolean }) =>
    api<SlaPolicy>(`/sla-policies/${id}`, { method: "PATCH", body }));
export const useDeleteSlaPolicy = () => useSlaPolicyChange((id: number) => api<undefined>(`/sla-policies/${id}`, { method: "DELETE" }));

export const useSlaAnalytics = (days: number) =>
  useQuery({ queryKey: ["analytics", "sla", days], queryFn: () => api<SlaAnalytics>("/analytics/sla", { query: { days } }), ...keep });

// ------------------------------------------------------------------ admin: event pipeline and DLQ
export const usePipelineStatus = () =>
  useQuery({ queryKey: ["pipeline"], queryFn: () => api<PipelineStatus>("/admin/events"), refetchInterval: 5000 });

export const useDeadLetters = (status: "waiting" | "replayed" | "discarded") =>
  useQuery({
    queryKey: ["dlq", status],
    queryFn: () => api<Page<DeadLetter>>("/admin/dlq", { query: { status, page_size: 100 } }),
    refetchInterval: 5000,
  });

function useDlqAction(path: (id: number) => string, body?: unknown) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<DeadLetter>(path(id), { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dlq"] });
      void qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });
}

export const useReplayDeadLetter = () => useDlqAction((id) => `/admin/dlq/${id}/replay`);
export const useDiscardDeadLetter = () => useDlqAction((id) => `/admin/dlq/${id}/discard`, {});

// ------------------------------------------------------------------ admin: users, teams, departments, categories
export const useUsers = (query: Query) =>
  useQuery({ queryKey: ["users", query], queryFn: () => api<Page<User>>("/users", { query }), ...keep });

export const useTeams = () => useQuery({ queryKey: ["teams"], queryFn: () => api<TeamInfo[]>("/teams"), staleTime: 60_000 });

export const useDepartments = () =>
  useQuery({ queryKey: ["departments"], queryFn: () => api<Department[]>("/departments"), staleTime: 5 * 60_000 });

function useAdminMutation<TVars, TResult>(fn: (v: TVars) => Promise<TResult>, invalidate: string[][]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => invalidate.forEach((queryKey) => void qc.invalidateQueries({ queryKey })),
  });
}

export const useCreateUser = () =>
  useAdminMutation((body: UserInput) => api<User>("/users", { method: "POST", body }), [["users"], ["teams"]]);

export const useUpdateUser = () =>
  useAdminMutation(({ id, ...body }: UserPatch & { id: number }) => api<User>(`/users/${id}`, { method: "PATCH", body }),
    [["users"], ["teams"]]);

export const useCreateTeam = () =>
  useAdminMutation((body: { name: string; department_id: number; description?: string | null }) =>
    api<TeamInfo>("/teams", { method: "POST", body }), [["teams"]]);

export const useUpdateTeam = () =>
  useAdminMutation(({ id, ...body }: { id: number; name?: string; department_id?: number; description?: string | null }) =>
    api<TeamInfo>(`/teams/${id}`, { method: "PATCH", body }), [["teams"], ["users"], ["categories"]]);

export const useDeleteTeam = () =>
  useAdminMutation((id: number) => api<void>(`/teams/${id}`, { method: "DELETE" }), [["teams"]]);

export const useCreateCategory = () =>
  useAdminMutation((body: { name: string; description?: string | null; team_id?: number | null }) =>
    api<CategoryInfo>("/categories", { method: "POST", body }), [["categories"], ["teams"]]);

export const useUpdateCategory = () =>
  useAdminMutation(({ id, ...body }: { id: number; name?: string; description?: string | null; team_id?: number | null; clear_team?: boolean }) =>
    api<CategoryInfo>(`/categories/${id}`, { method: "PATCH", body }), [["categories"], ["teams"]]);

export const useDeleteCategory = () =>
  useAdminMutation((id: number) => api<void>(`/categories/${id}`, { method: "DELETE" }), [["categories"], ["teams"]]);
