import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { TicketDetail } from "@/api/types";
import { ticket } from "@/test/fixtures";
import { adminUser, agentUser, mockFetch, renderRoute, signedInAs } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const now = new Date().toISOString();
const bodyOf = (init?: RequestInit) => JSON.parse(String(init?.body ?? "{}"));

const lowConfidence: TicketDetail = {
  ...ticket,
  needs_review: true,
  category_confidence: 0.31,
  team: null,
  top_categories: [["Payments related", 0.31], ["Refund Related", 0.27], ["Returns", 0.12]],
  allowed_actions: ["assign", "escalate"],
};

const routedTo = (patch: Partial<TicketDetail>): TicketDetail => ({
  ...ticket,
  status: "ASSIGNED",
  needs_review: false,
  labels_from: "human",
  assignee: { id: 2, name: "Arjun Agent" },
  team: { id: 3, name: "Payments Support" },
  allowed_actions: ["assign", "start", "escalate", "resolve"],
  timeline: [
    ...ticket.timeline,
    { id: 3, event_type: "routed", actor: null, created_at: now,
      metadata: { outcome: "assigned", rule: "LEAST_BUSY", assignee: "Arjun Agent", team: "Payments Support", reason: "Least busy of 3 available agents in Payments Support (0 open)." } },
    { id: 4, event_type: "status_changed", actor: null, created_at: now, metadata: { from: "TRIAGED", to: "ASSIGNED", trigger: "triage" } },
  ],
  ...patch,
});

describe("review queue", () => {
  it("confirming the AI category routes the ticket and reports where it went", async () => {
    let reviewed = false;
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/api/v1/tickets/1") && i?.method === "PATCH" ? ((reviewed = true), { body: routedTo({}) }) : undefined),
      (u) => (u.includes("/api/v1/tickets?") && u.includes("needs_review=true")
        ? { body: { items: reviewed ? [] : [lowConfidence], total: reviewed ? 0 : 1, page: 1, page_size: 20 } } : undefined),
      (u) => (u.includes("/api/v1/categories") ? { body: [{ name: "Payments related" }, { name: "Refund Related" }, { name: "Returns" }] } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/review");
    const list = await screen.findByRole("list", { name: "Tickets to review" });
    expect(within(list).getByText("31%")).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: /Refund Related 27%/ })).toBeInTheDocument();

    await userEvent.click(within(list).getByRole("button", { name: "Confirm Payments related" }));
    const done = await screen.findByRole("list", { name: "Just reviewed" });
    expect(done).toHaveTextContent("Payments Support · Arjun Agent");
    expect(await screen.findByText("Nothing to review")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/tickets/1") && i?.method === "PATCH")!;
    expect(bodyOf(call[1])).toEqual({ category: "Payments related" });
  });

  it("is an Admin screen: agents get no nav link and a no-access page", async () => {
    mockFetch(
      (u) => (u.includes("/api/v1/tickets/summary") ? { body: { by_status: {}, open: 0 } } : undefined),
      signedInAs(agentUser),
      () => ({ body: { items: [], total: 0, page: 1, page_size: 25 } }),
    );
    renderRoute(<App />, "/review");
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Main" })).queryByRole("link", { name: "Review queue" })).toBeNull();
  });
});

describe("routing on the ticket page", () => {
  it("timeline and assignment card explain the routing decision", async () => {
    mockFetch((u) => (u.split("?")[0].endsWith("/api/v1/tickets/1") ? { body: routedTo({}) } : undefined), signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/tickets/1");
    const timeline = await screen.findByRole("list", { name: "Ticket timeline" });
    expect(timeline).toHaveTextContent("Routing rules: assigned to Arjun Agent in Payments Support");
    expect(timeline).toHaveTextContent("Routing rules moved it from Triaged to Assigned");
    expect(screen.getAllByText("Least busy of 3 available agents in Payments Support (0 open).").length).toBe(2);
  });

  it("a confirmation by an Admin is shown as the person's step, the routing as the rules'", async () => {
    const confirmed = routedTo({
      timeline: [
        ...ticket.timeline,
        { id: 3, event_type: "category_confirmed", actor: { id: 1, name: "Ada Admin" }, metadata: { category: "Payments related" }, created_at: now },
        { id: 4, event_type: "routed", actor: { id: 1, name: "Ada Admin" }, created_at: now,
          metadata: { outcome: "assigned", trigger: "category_confirmed", assignee: "Arjun Agent", team: "Payments Support", reason: "Least busy." } },
        { id: 5, event_type: "status_changed", actor: { id: 1, name: "Ada Admin" }, created_at: now, metadata: { from: "TRIAGED", to: "ASSIGNED", trigger: "category_confirmed" } },
        { id: 6, event_type: "routed", actor: { id: 1, name: "Ada Admin" }, created_at: now,
          metadata: { outcome: "team_queue", trigger: "manual", team: "Payments Support", reason: "All busy." } },
      ],
    });
    mockFetch((u) => (u.split("?")[0].endsWith("/api/v1/tickets/1") ? { body: confirmed } : undefined), signedInAs(adminUser), () => ({ body: [] }));
    renderRoute(<App />, "/tickets/1");
    const timeline = await screen.findByRole("list", { name: "Ticket timeline" });
    expect(timeline).toHaveTextContent("Ada Admin confirmed the AI category Payments related");
    expect(timeline).toHaveTextContent("Routing rules: assigned to Arjun Agent");
    expect(timeline).toHaveTextContent("Routing rules moved it from Triaged to Assigned");
    expect(timeline).toHaveTextContent("Ada Admin re-ran routing: queued for Payments Support");
    expect(screen.getByText("AI category confirmed by a person")).toBeInTheDocument();
  });

  it("a low-confidence ticket offers confirm and the top alternatives", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/api/v1/tickets/1") && i?.method === "PATCH" ? { body: routedTo({ category: "Refund Related" }) } : undefined),
      (u) => (u.split("?")[0].endsWith("/api/v1/tickets/1") ? { body: lowConfidence } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    expect(await screen.findByText(/not routed until a person confirms the category/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm Payments related" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Refund Related 27%/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/tickets/1") && i?.method === "PATCH")).toBe(true));
    expect(await screen.findByRole("button", { name: "Start work" })).toBeInTheDocument(); // routed, ASSIGNED
  });

  it("admins can re-run routing on a queued ticket", async () => {
    const queued: TicketDetail = { ...ticket, allowed_actions: ["auto_assign", "assign", "escalate"] };
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/tickets/1/auto-assign") && i?.method === "POST" ? { body: routedTo({}) } : undefined),
      (u) => (u.split("?")[0].endsWith("/api/v1/tickets/1") ? { body: queued } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: "Auto-assign" }));
    expect(await screen.findByRole("button", { name: "Start work" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/auto-assign"))).toBe(true);
  });

  it("a category fix that routes the ticket to another team says where it went", async () => {
    const mine: TicketDetail = { ...routedTo({}), allowed_actions: ["assign", "start", "escalate", "resolve"] };
    mockFetch(
      (u, i) => (u.endsWith("/api/v1/tickets/1") && i?.method === "PATCH"
        ? { body: routedTo({ category: "Returns", team: { id: 4, name: "Returns & Pickups" }, assignee: { id: 5, name: "Olga Other" }, can_view: false, allowed_actions: [] }) }
        : undefined),
      (u) => (u.split("?")[0].endsWith("/api/v1/tickets/1") ? { body: mine } : undefined),
      (u) => (u.includes("/api/v1/categories") ? { body: [{ name: "Payments related" }, { name: "Returns" }] } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await screen.findByRole("option", { name: "Returns" }); // categories loaded
    await userEvent.selectOptions(screen.getByLabelText("Correct category"), "Returns");
    expect(await screen.findByText("INC-00001 moved to Returns & Pickups")).toBeInTheDocument();
    expect(screen.getByText(/gave it to Olga Other/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to My work" })).toBeInTheDocument();
  });
});
