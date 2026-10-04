import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

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
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        {ui}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const health = { status: "ok", classifier: "triage-v1", sentiment_model: "nlptown", llm_provider: "mock" };
