import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  Analysis,
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
  TriagePreview,
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

export const useTicket = (id: number) =>
  useQuery({ queryKey: ["ticket", id], queryFn: () => api<TicketDetail>(`/tickets/${id}`), enabled: Number.isFinite(id) });

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

export function useUpdateTicket(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { status?: string; category?: string }) => api<TicketDetail>(`/tickets/${id}`, { method: "PATCH", body }),
    onSuccess: (data) => {
      qc.setQueryData(["ticket", id], data);
      void qc.invalidateQueries({ queryKey: ["tickets"] });
      void qc.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

export function useDraftResponse(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<Analysis>("/ai/draft-response", { method: "POST", body: { ticket_id: id } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["ticket", id] }),
  });
}

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
