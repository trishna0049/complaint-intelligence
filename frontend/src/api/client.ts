import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  Analysis,
  CategoryBreakdowns,
  Emerging,
  Granularity,
  Overview,
  Page,
  Ticket,
  TicketDetail,
  TicketInput,
  Trends,
  TriagePreview,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public details?: unknown,
    /** Machine-readable error code from the API, e.g. "llm_rate_limited". */
    public code?: string,
    /** Seconds to wait before retrying (from the Retry-After header), when the API sends one. */
    public retryAfter?: number,
  ) {
    super(message);
  }
}

/** Every request goes to the versioned API. */
export const API_BASE = "/api/v1";

type Query = Record<string, string | number | boolean | undefined | null>;

export async function api<T>(path: string, init: { method?: string; body?: unknown; query?: Query } = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(init.query ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}${qs.toString() ? `?${qs}` : ""}`, {
      method: init.method ?? "GET",
      headers: init.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Can't reach the API. Is the backend running?", undefined, "network_error");
  }
  if (!res.ok) {
    let message = res.statusText || "Request failed";
    let details: unknown;
    let code: string | undefined;
    try {
      const body = await res.json();
      details = body.detail;
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
      else if (body.detail && typeof body.detail.message === "string") {
        // Typed errors, e.g. LLM failures: {detail: {code, message}}
        message = body.detail.message;
        code = body.detail.code;
      }
    } catch {
      /* not JSON */
    }
    const retry = Number(res.headers.get("Retry-After"));
    throw new ApiError(res.status, message, details, code, Number.isFinite(retry) && retry > 0 ? retry : undefined);
  }
  return (await res.json()) as T;
}

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
  useQuery({ queryKey: ["categories"], queryFn: () => api<{ name: string; base_priority: string }[]>("/categories"), staleTime: Infinity });

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
