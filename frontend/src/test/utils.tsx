import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { setAccessToken } from "@/api/http";
import type { User } from "@/api/types";
import { AuthProvider } from "@/auth/AuthProvider";

type Handler = (
  url: string,
  init?: RequestInit,
) => { status?: number; body?: unknown; headers?: Record<string, string>; throws?: boolean } | undefined;

/** Mock global fetch: handlers are tried in order; unmatched requests return 404. */
export function mockFetch(...handlers: Handler[]) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    for (const h of handlers) {
      const r = h(url, init);
      if (r?.throws) throw new TypeError("Failed to fetch");
      if (r) {
        if (r.status === 204) return new Response(null, { status: 204 });
        return new Response(JSON.stringify(r.body ?? {}), {
          status: r.status ?? 200,
          headers: { "Content-Type": "application/json", ...(r.headers ?? {}) },
        });
      }
    }
    return new Response(JSON.stringify({ detail: `unmocked ${url}` }), { status: 404 });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export function renderRoute(ui: ReactElement, route = "/") {
  setAccessToken(null);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const health = { status: "ok", classifier: "triage-v1", sentiment_model: "nlptown", llm_provider: "mock" };

const now = new Date().toISOString();
export const adminUser: User = {
  id: 1, name: "Ada Admin", email: "admin@shopzilla.example", role: "ADMIN", team: null, is_active: true,
  source: "app", supervisor: null, last_login_at: now, created_at: now,
};
export const agentUser: User = {
  id: 2, name: "Arjun Agent", email: "arjun@shopzilla.example", role: "AGENT", team: { id: 3, name: "Payments Support" },
  is_active: true, source: "dataset", supervisor: "Mason Gupta", last_login_at: now, created_at: now,
};

export const session = (user: User) => ({ access_token: `token-${user.id}`, token_type: "bearer", expires_in: 900, user });

/** Signed-in session restored from the refresh cookie (plus logout and health). */
export function signedInAs(user: User | null): Handler {
  return (u, i) => {
    if (u.endsWith("/api/v1/auth/refresh") && i?.method === "POST") {
      return user ? { body: session(user) } : { status: 401, body: { detail: { code: "no_refresh_token", message: "Sign in to continue." } } };
    }
    if (u.endsWith("/api/v1/auth/logout")) return { status: 204 };
    if (u.includes("/api/v1/health")) return { body: health };
    // The app shell opens the live notification stream and the bell reads the list.
    if (u.includes("/api/v1/notifications/stream")) return { status: 204 };
    if (u.includes("/api/v1/notifications?")) return { body: { items: [], total: 0, page: 1, page_size: 8, unread: 0 } };
    return undefined;
  };
}
