import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { ComplaintDetail, Dashboard } from "@/api/types";
import { ConfidenceMeter, PriorityBadge } from "@/components/Badges";
import { health, mockFetch, renderRoute } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const complaint: ComplaintDetail = {
  id: 1, reference: "CMP-000001", subject: "Charged twice for my order", channel: "Email", status: "Open",
  category: "Payments related", intent: "Online Payment Issues", sentiment: "Very Negative", priority: "Critical",
  category_confidence: 0.82, needs_review: false, source: "new", text_is_template: false, customer_name: "Ravi Kumar",
  city: "Pune", created_at: new Date().toISOString(),
  text: "I was charged twice for my order of ₹12,500 and have already contacted support three times.",
  order_id: null, product: "Mobile", amount_inr: 12500, csat_score: null, resolved_at: null, intent_confidence: 0.4,
  sentiment_score: 1.3, priority_reasons: [{ rule: "BASE", reason: "Base priority for Payments related", from: "", to: "High" },
    { rule: "R1", reason: "Very negative sentiment", from: "High", to: "Critical" }],
  entities: { amounts: [{ text: "₹12,500", value: 12500 }], max_amount_inr: 12500, order_ids: [], dates: [], products: [], repeat_contact: true },
  labels_from: "model", model_version: "triage-v1", insight: null,
};

const dashboard: Dashboard = {
  window_days: 30, generated_at: new Date().toISOString(),
  kpis: { total: 1200, open: 40, high_priority: 300, critical: 25, negative_share: 0.31, avg_csat: 4.2, avg_sentiment_score: 3.6,
    total_change_pct: 12, high_priority_change_pct: -5, needs_review: 3, open_high_priority: 7 },
  trend: [{ date: "2026-09-30", total: 40, "Very Negative": 5, Negative: 3, Neutral: 2, Positive: 10, "Very Positive": 20, high_priority: 9, avg_csat: 4.1 }],
  categories: [{ name: "Returns", count: 600, negative_share: 0.2, high_priority: 50 }],
  intents: [{ name: "Reverse Pickup Enquiry", count: 300, negative_share: 0.1, high_priority: 10 }],
  channels: [{ name: "Inbound", count: 900, negative_share: 0.3, high_priority: 200 }],
  priorities: [{ name: "Medium", count: 800, negative_share: 0.2, high_priority: 0 }],
  sentiment: [{ name: "Very Negative", count: 100 }, { name: "Negative", count: 50 }, { name: "Neutral", count: 30 }, { name: "Positive", count: 200 }, { name: "Very Positive", count: 400 }],
  high_priority_open: [{ id: 1, reference: "CMP-000001", subject: "Charged twice for my order", category: "Payments related", priority: "Critical", sentiment: "Very Negative", created_at: new Date().toISOString() }],
  emerging: [{ category: "Refund Related", this_week: 182, last_week: 127, change_pct: 43.3, negative_share: 0.4 }],
  insights: ["Refund Related complaints rose 43% this week (182 vs 127 the week before)."],
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
  it("dashboard shows KPIs, the generated insight and emerging issues", async () => {
    mockFetch((u) => (u.includes("/api/dashboard") ? { body: dashboard } : undefined), (u) => (u.includes("/api/health") ? { body: health } : undefined));
    renderRoute(<App />, "/");
    expect(await screen.findByText("1,200")).toBeInTheDocument();
    expect(screen.getByText(/Refund Related complaints rose 43%/)).toBeInTheDocument();
    expect(screen.getByText("+43%")).toBeInTheDocument();
    expect(screen.getByText("Charged twice for my order")).toBeInTheDocument();
  });

  it("complaints list renders triage columns", async () => {
    mockFetch(
      (u) => (u.includes("/api/complaints?") ? { body: { items: [complaint], total: 1, page: 1, page_size: 25 } } : undefined),
      (u) => (u.includes("/api/categories") ? { body: [{ name: "Payments related", base_priority: "High" }] } : undefined),
      (u) => (u.includes("/api/health") ? { body: health } : undefined),
    );
    renderRoute(<App />, "/complaints");
    expect(await screen.findByText("CMP-000001")).toBeInTheDocument();
    const row = screen.getByText("CMP-000001").closest("tr")!;
    expect(row).toHaveTextContent("Very Negative");
    expect(row).toHaveTextContent("Critical");
    expect(row).toHaveTextContent("Payments related");
  });

  it("new complaint validates, previews triage, then saves", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/api/triage") && i?.method === "POST" ? { body: {
        category: "Payments related", category_confidence: 0.82, top_categories: [["Payments related", 0.82], ["Refund Related", 0.1]],
        intent: "Online Payment Issues", intent_confidence: 0.4, sentiment: "Very Negative", sentiment_score: 1.3, priority: "Critical",
        priority_reasons: complaint.priority_reasons, entities: complaint.entities, needs_review: false, model_version: "triage-v1" } } : undefined),
      (u, i) => (u.endsWith("/api/complaints") && i?.method === "POST" ? { status: 201, body: complaint } : undefined),
      (u) => (u.includes("/api/complaints/1") ? { body: complaint } : undefined),
      (u) => (u.includes("/api/health") ? { body: health } : undefined),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/complaints/new");
    await userEvent.click(await screen.findByRole("button", { name: "Save complaint" }));
    expect(screen.getByText(/at least 5 characters/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Complaint text"), complaint.text);
    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));
    expect(await screen.findByText("Payments related")).toBeInTheDocument();
    expect(screen.getByText("Very negative sentiment")).toBeInTheDocument();
    expect(screen.getByText("Repeat contact")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save complaint" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/api/complaints") && i?.method === "POST")).toBe(true));
    expect(await screen.findByRole("heading", { name: "Charged twice for my order" })).toBeInTheDocument();
  });

  it("detail page generates AI insights on demand", async () => {
    let withInsight = false;
    const insight = { id: 5, summary: "Customer reports a payment problem.", key_issues: ["Payment problem", "Amount involved: ₹12,500"],
      recommended_actions: ["Check the payment gateway logs"], customer_reply: "Hello, I'm sorry…", provider: "mock",
      model: "mock-insight-v1", prompt_version: "insight-v1", created_at: new Date().toISOString() };
    mockFetch(
      (u, i) => (u.endsWith("/insights") && i?.method === "POST" ? ((withInsight = true), { status: 201, body: insight }) : undefined),
      (u) => (u.includes("/api/complaints/1") ? { body: { ...complaint, insight: withInsight ? insight : null } } : undefined),
      (u) => (u.includes("/api/health") ? { body: health } : undefined),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/complaints/1");
    await userEvent.click(await screen.findByRole("button", { name: /Generate insights/ }));
    expect(await screen.findByText("Customer reports a payment problem.")).toBeInTheDocument();
    expect(screen.getByText("Check the payment gateway logs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Regenerate/ })).toBeInTheDocument();
  });
});

describe("insight errors are shown clearly, not crashes", () => {
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
        if (!(u.endsWith("/insights") && i?.method === "POST")) return undefined;
        return { status, body: { detail: { code, message } }, headers: retry ? { "Retry-After": retry } : undefined };
      },
      (u) => (u.includes("/api/complaints/1") ? { body: complaint } : undefined),
      (u) => (u.includes("/api/health") ? { body: health } : undefined),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/complaints/1");
    await userEvent.click(await screen.findByRole("button", { name: /Generate insights/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(title);
    expect(alert).toHaveTextContent(message);
    if (retry) expect(alert).toHaveTextContent(`You can retry in ${retry} s.`);
    // The page is still usable: complaint text visible and the button can be pressed again.
    expect(screen.getByRole("heading", { name: "Charged twice for my order" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate insights/ })).toBeEnabled();
  });

  it("backend down → clear network message", async () => {
    mockFetch(
      (u, i) => (u.endsWith("/insights") && i?.method === "POST" ? { throws: true } : undefined),
      (u) => (u.includes("/api/complaints/1") ? { body: complaint } : undefined),
      (u) => (u.includes("/api/health") ? { body: health } : undefined),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/complaints/1");
    await userEvent.click(await screen.findByRole("button", { name: /Generate insights/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the API. Is the backend running?");
  });
});
