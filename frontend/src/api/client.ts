import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Complaint, ComplaintDetail, ComplaintInput, Dashboard, Insight, Page, TriagePreview } from "./types";

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

type Query = Record<string, string | number | boolean | undefined | null>;

export async function api<T>(path: string, init: { method?: string; body?: unknown; query?: Query } = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(init.query ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  let res: Response;
  try {
    res = await fetch(`/api${path}${qs.toString() ? `?${qs}` : ""}`, {
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

export const useDashboard = (days: number) =>
  useQuery({ queryKey: ["dashboard", days], queryFn: () => api<Dashboard>("/dashboard", { query: { days } }), placeholderData: keepPreviousData });

export const useComplaints = (query: Query) =>
  useQuery({ queryKey: ["complaints", query], queryFn: () => api<Page<Complaint>>("/complaints", { query }), placeholderData: keepPreviousData });

export const useComplaint = (id: number) =>
  useQuery({ queryKey: ["complaint", id], queryFn: () => api<ComplaintDetail>(`/complaints/${id}`), enabled: Number.isFinite(id) });

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: () => api<{ classifier: string | null; sentiment_model: string; llm_provider: string }>("/health"), staleTime: 60_000 });

export const useCategories = () =>
  useQuery({ queryKey: ["categories"], queryFn: () => api<{ name: string; base_priority: string }[]>("/categories"), staleTime: Infinity });

export function useCreateComplaint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ComplaintInput) => api<ComplaintDetail>("/complaints", { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["complaints"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export const useTriagePreview = () =>
  useMutation({ mutationFn: (body: ComplaintInput) => api<TriagePreview>("/triage", { method: "POST", body }) });

export function useUpdateComplaint(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { status?: string; category?: string }) => api<ComplaintDetail>(`/complaints/${id}`, { method: "PATCH", body }),
    onSuccess: (data) => {
      qc.setQueryData(["complaint", id], data);
      void qc.invalidateQueries({ queryKey: ["complaints"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useGenerateInsight(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<Insight>(`/complaints/${id}/insights`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["complaint", id] }),
  });
}
