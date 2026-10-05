import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { Analysis, CategoryBreakdowns, Emerging, Overview, Trends } from "@/api/types";
import { ConfidenceMeter, PriorityBadge } from "@/components/Badges";
import { ticket } from "@/test/fixtures";
import { adminUser, mockFetch, renderRoute, signedInAs } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());


const overview: Overview = {
  window_days: 30, generated_at: new Date().toISOString(),
  kpis: { total: 1200, open: 40, high_priority: 300, critical: 25, negative_share: 0.31, avg_csat: 4.2, avg_sentiment_score: 3.6,
    total_change_pct: 12, high_priority_change_pct: -5, needs_review: 3, open_high_priority: 7 },
  high_priority_open: [{ id: 1, ticket_number: "INC-00001", subject: "Charged twice for my order", category: "Payments related", priority: "Critical", sentiment: "Very Negative", created_at: new Date().toISOString() }],
  insights: ["Refund Related complaints rose 43% this week (182 vs 127 the week before)."],
};
const trends: Trends = {
  window_days: 30, granularity: "day",
  points: [{ date: "2026-09-30", total: 40, "Very Negative": 5, Negative: 3, Neutral: 2, Positive: 10, "Very Positive": 20, high_priority: 9, avg_csat: 4.1 }],
};
const breakdowns: CategoryBreakdowns = {
  window_days: 30,
  categories: [{ name: "Returns", count: 600, negative_share: 0.2, high_priority: 50 }],
  intents: [{ name: "Reverse Pickup Enquiry", count: 300, negative_share: 0.1, high_priority: 10 }],
  channels: [{ name: "Inbound", count: 900, negative_share: 0.3, high_priority: 200 }],
  priorities: [{ name: "Medium", count: 800, negative_share: 0.2, high_priority: 0 }],
  sentiment: [{ name: "Very Negative", count: 100 }, { name: "Negative", count: 50 }, { name: "Neutral", count: 30 }, { name: "Positive", count: 200 }, { name: "Very Positive", count: 400 }],
};
const emerging: Emerging = {
  generated_at: new Date().toISOString(),
  emerging: [{ category: "Refund Related", this_week: 182, last_week: 127, change_pct: 43.3, negative_share: 0.4 }],
};

const copilot: Analysis = {
  id: 5, kind: "copilot", category: "Payments related", intent: "Online Payment Issues", sentiment: "Very Negative", priority: "Critical",
  confidence: 0.82, summary: "Customer reports a payment problem.", key_issues: ["Payment problem", "Amount involved: ₹12,500"],
  recommendations: ["Check the payment gateway logs"], draft_response: "Hello, I'm sorry…", provider: "mock",
  model: "mock-copilot-v2", model_version: "triage-v1", prompt_version: "copilot-v2", usage: null, created_at: new Date().toISOString(),
  root_cause: "Likely a duplicate capture at the payment gateway.", draft_status: "pending", reviewed_by: null, reviewed_at: null,
  final_response: null, edited: null, comment_id: null, discard_reason: null,
};

describe("components", () => {
  it("priority badge carries a text label, not colour alone", () => {
    render(<PriorityBadge priority="Critical" />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });
  it("confidence meter shows a percentage", () => {
    render(<ConfidenceMeter value={0.823} />);
    expect(screen.getByText("82%")).toBeInTheDocument();
  });
});

describe("pages", () => {
  it("dashboard shows KPIs, the generated insight and emerging issues from the analytics endpoints", async () => {
    const fetchMock = mockFetch(
      (u) => (u.includes("/api/v1/analytics/overview") ? { body: overview } : undefined),
      (u) => (u.includes("/api/v1/analytics/trends") ? { body: trends } : undefined),
      (u) => (u.includes("/api/v1/analytics/categories") ? { body: breakdowns } : undefined),
      (u) => (u.includes("/api/v1/analytics/emerging") ? { body: emerging } : undefined),
      signedInAs(adminUser),
    );
    renderRoute(<App />, "/");
    expect(await screen.findByText("1,200")).toBeInTheDocument();
    expect(screen.getByText(/Refund Related complaints rose 43%/)).toBeInTheDocument();
    expect(await screen.findByText("+43%")).toBeInTheDocument();
    expect(screen.getByText("Charged twice for my order")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Week" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("granularity=week"))).toBe(true));
  });

  it("ticket list renders triage columns", async () => {
    mockFetch(
      (u) => (u.includes("/api/v1/tickets?") ? { body: { items: [ticket], total: 1, page: 1, page_size: 25 } } : undefined),
      (u) => (u.includes("/api/v1/categories") ? { body: [{ name: "Payments related", base_priority: "High" }] } : undefined),
      signedInAs(adminUser),
    );
    renderRoute(<App />, "/tickets");
    expect(await screen.findByText("INC-00001")).toBeInTheDocument();
    const row = screen.getByText("INC-00001").closest("tr")!;
    expect(row).toHaveTextContent("Very Negative");
    expect(row).toHaveTextContent("Critical");
    expect(row).toHaveTextContent("Payments related");
  });

  it("old /complaints links redirect to tickets", async () => {
    mockFetch(
      (u) => (u.includes("/api/v1/tickets/1") ? { body: ticket } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/complaints/1");
    expect(await screen.findByRole("heading", { name: "Charged twice for my order" })).toBeInTheDocument();
  });

  it("create ticket validates, previews triage, then saves", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/api/v1/ai/analyze") && i?.method === "POST" ? { body: {
        category: "Payments related", category_confidence: 0.82, top_categories: [["Payments related", 0.82], ["Refund Related", 0.1]],
        intent: "Online Payment Issues", intent_confidence: 0.4, sentiment: "Very Negative", sentiment_score: 1.3, priority: "Critical",
        priority_reasons: ticket.priority_reasons, entities: ticket.entities, needs_review: false, model_version: "triage-v1" } } : undefined),
      (u, i) => (u.endsWith("/api/v1/tickets") && i?.method === "POST" ? { status: 201, body: ticket } : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: ticket } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/new");
    await userEvent.click(await screen.findByRole("button", { name: "Create ticket" }));
    expect(screen.getByText(/at least 5 characters/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Complaint description"), ticket.description);
    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));
    expect(await screen.findByText("Payments related")).toBeInTheDocument();
    expect(screen.getByText("Very negative sentiment")).toBeInTheDocument();
    expect(screen.getByText("Repeat contact")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Create ticket" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/api/v1/tickets") && i?.method === "POST")).toBe(true));
    expect(await screen.findByRole("heading", { name: "Charged twice for my order" })).toBeInTheDocument();
  });

  it("detail page runs the copilot on demand", async () => {
    let withCopilot = false;
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/api/v1/ai/draft-response") && i?.method === "POST" ? ((withCopilot = true), { status: 201, body: copilot }) : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: { ...ticket, copilot: withCopilot ? copilot : null } } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: /Run copilot/ }));
    expect(await screen.findByText("Customer reports a payment problem.")).toBeInTheDocument();
    expect(screen.getByText("Check the payment gateway logs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Regenerate/ })).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/ai/draft-response"))!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({ ticket_id: 1 });
  });
});

describe("copilot errors are shown clearly, not crashes", () => {
  const cases = [
    { status: 502, code: "llm_auth_failed", title: "OpenAI API key rejected",
      message: "OpenAI rejected the API key. Check OPENAI_API_KEY in .env and restart the backend.", retry: undefined },
    { status: 504, code: "llm_timeout", title: "OpenAI timed out",
      message: "OpenAI did not respond within 30 s. Try again.", retry: undefined },
    { status: 429, code: "llm_rate_limited", title: "OpenAI rate limit reached",
      message: "OpenAI rate limit reached. Try again in about 20 s.", retry: "20" },
  ];

  it.each(cases)("$code → alert with title and message", async ({ status, code, title, message, retry }) => {
    mockFetch(
      (u, i) => {
        if (!(u.endsWith("/ai/draft-response") && i?.method === "POST")) return undefined;
        return { status, body: { detail: { code, message } }, headers: retry ? { "Retry-After": retry } : undefined };
      },
      (u) => (u.includes("/api/v1/tickets/1") ? { body: ticket } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: /Run copilot/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(title);
    expect(alert).toHaveTextContent(message);
    if (retry) expect(alert).toHaveTextContent(`You can retry in ${retry} s.`);
    // The page is still usable: ticket visible and the button can be pressed again.
    expect(screen.getByRole("heading", { name: "Charged twice for my order" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run copilot/ })).toBeEnabled();
  });

  it("backend down → clear network message", async () => {
    mockFetch(
      (u, i) => (u.endsWith("/ai/draft-response") && i?.method === "POST" ? { throws: true } : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: ticket } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: /Run copilot/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the API. Is the backend running?");
  });
});
