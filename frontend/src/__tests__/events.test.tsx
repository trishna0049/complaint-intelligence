import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { DeadLetter, PipelineStatus, TicketDetail } from "@/api/types";
import { ticket } from "@/test/fixtures";
import { adminUser, agentUser, mockFetch, renderRoute, signedInAs } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const now = new Date().toISOString();
const isTicket1 = (u: string) => u.split("?")[0].endsWith("/api/v1/tickets/1");
const fresh: TicketDetail = {
  ...ticket, status: "NEW", category: null, intent: null, sentiment: null, category_confidence: null, priority_reasons: null,
  entities: null, team: null, timeline: [ticket.timeline[0]], allowed_actions: ["assign"],
  pipeline: { triage: "pending", copilot: "drafting" }, created_at: now,
};

describe("asynchronous triage on the ticket page", () => {
  it("shows the AI worker at work, then the triage when it lands", async () => {
    let calls = 0;
    mockFetch(
      (u) => (isTicket1(u) ? ((calls += 1), { body: calls < 2 ? fresh : { ...ticket, pipeline: { triage: "done", copilot: "drafting" } } }) : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    expect(await screen.findByText(/The AI worker is triaging this ticket/)).toBeInTheDocument();
    expect(screen.getAllByText("Triaging…").length).toBeGreaterThan(0);
    expect(screen.getByText(/The LLM worker is drafting/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Correct category")).toBeNull();
    // Polled every 1.5 s while the workers are busy.
    await waitFor(() => expect(screen.queryByText(/The AI worker is triaging/)).toBeNull(), { timeout: 4000 });
    expect(screen.getAllByText("Payments related").length).toBeGreaterThan(0);
    expect(screen.queryByText("Triaging…")).toBeNull();
    expect(calls).toBeGreaterThanOrEqual(2);
  });

  it("explains failures that wait in the dead-letter queue", async () => {
    mockFetch(
      (u) => (isTicket1(u) ? { body: { ...fresh, pipeline: { triage: "failed", copilot: "failed" } } } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    expect(await screen.findByText(/Automatic triage failed after its retries/)).toBeInTheDocument();
    expect(screen.getByText(/The automatic draft failed/)).toBeInTheDocument();
  });
});

const status: PipelineStatus = {
  mode: "kafka", prefix: "complaints", kafka_bootstrap_servers: "localhost:19092", retries: 3, kafka_ui_url: "http://localhost:18090",
  outbox: { pending: 0, oldest_pending_seconds: null, failing: 0, last_published_at: now },
  consumers: [
    { name: "ai-worker", description: "Triage, routing and embeddings", events: ["ticket.created"], processed_total: 120, processed_last_hour: 12, last_processed_at: now, dead_letters_waiting: 0 },
    { name: "llm-worker", description: "Copilot drafts after triage", events: ["ai.analysis.completed"], processed_total: 40, processed_last_hour: 4, last_processed_at: now, dead_letters_waiting: 1 },
  ],
};
const letter: DeadLetter = {
  id: 9, consumer: "llm-worker", event_id: "1df30bcd-e43d-4933-b8ee-c0b5a182f9f2", event_type: "ai.analysis.completed", ticket_id: 42,
  envelope: { type: "ai.analysis.completed", ticket_id: 42 }, error: "LLMError: OpenAI rate limit reached", attempts: 4,
  status: "waiting", failed_at: now, resolved_at: null, resolved_by_id: null,
};

describe("event pipeline (admin)", () => {
  it("shows the workers and replays a dead letter", async () => {
    let replayed = false;
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/admin/dlq/9/replay") && i?.method === "POST" ? ((replayed = true), { body: { ...letter, status: "replayed", resolved_at: now } }) : undefined),
      (u) => (u.includes("/admin/dlq") && u.includes("status=waiting") ? { body: { items: replayed ? [] : [letter], total: replayed ? 0 : 1, page: 1, page_size: 100 } } : undefined),
      (u) => (u.includes("/admin/dlq") ? { body: { items: [], total: 0, page: 1, page_size: 100 } } : undefined),
      (u) => (u.endsWith("/admin/events") ? { body: status } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/admin/events");
    const workers = await screen.findByRole("table", { name: "Workers" });
    expect(within(workers).getByText("ai-worker").closest("tr")).toHaveTextContent("120");
    expect(screen.getByRole("link", { name: /Kafka UI/ })).toHaveAttribute("href", "http://localhost:18090");
    const waiting = await screen.findByRole("list", { name: "waiting dead letters" });
    expect(waiting).toHaveTextContent("LLMError: OpenAI rate limit reached");
    expect(within(waiting).getByRole("link", { name: "ticket #42" })).toHaveAttribute("href", "/tickets/42");
    await userEvent.click(within(waiting).getByRole("button", { name: "Replay" }));
    expect(await screen.findByText("No failed events")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/admin/dlq/9/replay") && i?.method === "POST")).toBe(true);
  });

  it("discards and switches to the history tabs", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/admin/dlq/9/discard") && i?.method === "POST" ? { body: { ...letter, status: "discarded" } } : undefined),
      (u) => (u.includes("status=discarded") ? { body: { items: [{ ...letter, status: "discarded", resolved_at: now }], total: 1, page: 1, page_size: 100 } } : undefined),
      (u) => (u.includes("/admin/dlq") ? { body: { items: [letter], total: 1, page: 1, page_size: 100 } } : undefined),
      (u) => (u.endsWith("/admin/events") ? { body: status } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/admin/events");
    await userEvent.click(within(await screen.findByRole("list", { name: "waiting dead letters" })).getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/discard"))).toBe(true));
    await userEvent.click(screen.getByRole("tab", { name: "Discarded" }));
    expect(await screen.findByRole("list", { name: "discarded dead letters" })).toHaveTextContent("discarded");
  });

  it("is Admin only", async () => {
    mockFetch(signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/admin/events");
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
  });
});
