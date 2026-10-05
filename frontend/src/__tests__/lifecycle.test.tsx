import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { TicketDetail, TeamMember } from "@/api/types";
import { ticket } from "@/test/fixtures";
import { adminUser, agentUser, mockFetch, renderRoute, signedInAs } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const now = new Date().toISOString();
const inProgress: TicketDetail = {
  ...ticket,
  status: "IN_PROGRESS",
  assignee: { id: 2, name: "Arjun Agent" },
  allowed_actions: ["assign", "wait_customer", "escalate", "resolve"],
};
const bodyOf = (init?: RequestInit) => JSON.parse(String(init?.body ?? "{}"));

describe("ticket actions", () => {
  it("shows only the actions the API allows, primary first", async () => {
    mockFetch((u) => (u.includes("/api/v1/tickets/1") ? { body: inProgress } : undefined), signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/tickets/1");
    const bar = await screen.findByRole("toolbar", { name: "Ticket actions" });
    const labels = within(bar).getAllByRole("button").map((b) => b.textContent);
    expect(labels).toEqual(["Resolve", "Assign", "Wait on customer", "Escalate"]);
    expect(within(bar).queryByRole("button", { name: /Close/ })).toBeNull();
  });

  it("a ticket with no permitted actions says so instead of showing buttons", async () => {
    mockFetch((u) => (u.includes("/api/v1/tickets/1") ? { body: { ...ticket, allowed_actions: [] } } : undefined), signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/tickets/1");
    expect(await screen.findByText("No actions available to you on this ticket.")).toBeInTheDocument();
  });

  it("wait on customer is a direct PATCH to WAITING_CUSTOMER", async () => {
    let current: TicketDetail = inProgress;
    const fetchMock = mockFetch(
      (u, i) => {
        if (!(u.endsWith("/api/v1/tickets/1") && i?.method === "PATCH")) return undefined;
        current = { ...inProgress, status: "WAITING_CUSTOMER", allowed_actions: ["assign", "resume", "escalate", "resolve"] };
        return { body: current };
      },
      (u) => (u.includes("/api/v1/tickets/1") ? { body: current } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: "Wait on customer" }));
    expect(await screen.findByRole("button", { name: "Customer replied" })).toBeInTheDocument();
    expect(screen.getAllByText("Waiting on customer").length).toBeGreaterThan(0);
    const call = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/tickets/1") && i?.method === "PATCH")!;
    expect(bodyOf(call[1])).toEqual({ status: "WAITING_CUSTOMER" });
  });

  it("resolve asks for a resolution, validates it and posts it", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/tickets/1/resolve") && i?.method === "POST"
        ? { body: { ...inProgress, status: "RESOLVED", resolution: bodyOf(i).resolution, resolved_at: now, allowed_actions: ["close", "reopen"] } }
        : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: inProgress } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: "Resolve" }));
    const dialog = screen.getByRole("dialog", { name: "Resolve INC-00001" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Resolve" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("at least 3 characters");
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/resolve"))).toBe(false);

    await userEvent.type(within(dialog).getByLabelText("Resolution"), "Reversed the duplicate debit");
    await userEvent.click(within(dialog).getByRole("button", { name: "Resolve" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("Reversed the duplicate debit")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/resolve"))!;
    expect(bodyOf(call[1])).toEqual({ resolution: "Reversed the duplicate debit" });
  });

  it("an invalid move (409) is shown to the user and the page keeps working", async () => {
    mockFetch(
      (u, i) => (u.endsWith("/tickets/1/escalate") && i?.method === "POST"
        ? { status: 409, body: { detail: { code: "invalid_transition", message: "Can't escalate a ticket that is RESOLVED (allowed from: ASSIGNED)." } } }
        : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: inProgress } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: "Escalate" }));
    const dialog = screen.getByRole("dialog", { name: "Escalate INC-00001" });
    await userEvent.type(within(dialog).getByLabelText("Reason"), "Customer is threatening legal action");
    await userEvent.click(within(dialog).getByRole("button", { name: "Escalate" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Can't escalate a ticket that is RESOLVED");
  });

  it("admins assign by team; agents are sorted by open load and the least busy is marked", async () => {
    const members: TeamMember[] = [
      { id: 7, name: "Busy Bee", role: "AGENT", open_tickets: 9 },
      { id: 8, name: "Quiet Quinn", role: "AGENT", open_tickets: 1 },
    ];
    const fetchMock = mockFetch(
      (u) => (u.includes("/api/v1/teams/3/members") ? { body: members } : undefined),
      (u) => (u.endsWith("/api/v1/teams") ? { body: [{ id: 3, name: "Payments Support", description: null, department: null, member_count: 2, categories: [] }] } : undefined),
      (u, i) => (u.endsWith("/tickets/1/assign") && i?.method === "POST"
        ? { body: { ...ticket, status: "ASSIGNED", assignee: { id: 8, name: "Quiet Quinn" }, allowed_actions: ["assign", "start", "escalate", "resolve"] } }
        : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: ticket } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: "Assign" }));
    const dialog = screen.getByRole("dialog", { name: "Assign INC-00001" });
    const group = await within(dialog).findByRole("radiogroup", { name: "Agent" });
    const rows = within(group).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Quiet Quinn");
    expect(rows[0]).toHaveTextContent("Least busy");
    expect(rows[1]).toHaveTextContent("Busy Bee");

    await userEvent.click(within(dialog).getByLabelText("Quiet Quinn"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByRole("button", { name: "Start work" })).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/assign"))!;
    expect(bodyOf(call[1])).toEqual({ assignee_id: 8 });
  });
});

describe("conversation and timeline", () => {
  it("posts a comment and shows the refreshed thread", async () => {
    let comments: TicketDetail["comments"] = [];
    const fetchMock = mockFetch(
      (u, i) => {
        if (!(u.endsWith("/tickets/1/comments") && i?.method === "POST")) return undefined;
        comments = [{ id: 1, body: bodyOf(i).body, ai_assisted: false, author: { id: 2, name: "Arjun Agent" }, created_at: now }];
        return { status: 201, body: comments[0] };
      },
      (u) => (u.includes("/api/v1/tickets/1") ? { body: { ...inProgress, comments } } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    expect(await screen.findByText("No comments yet")).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Add comment" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Add a comment"), "Refund raised with the bank.");
    await userEvent.click(submit);
    expect(await screen.findByText("Refund raised with the bank.")).toBeInTheDocument();
    expect(screen.getByLabelText("Add a comment")).toHaveValue("");
    expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/comments") && i?.method === "POST")).toBe(true);
  });

  it("the timeline describes each event in plain words", async () => {
    const withHistory: TicketDetail = {
      ...inProgress,
      timeline: [
        ...ticket.timeline,
        { id: 3, event_type: "assigned", actor: { id: 1, name: "Ada Admin" }, metadata: { assignee: "Arjun Agent", note: "VIP customer" }, created_at: now },
        { id: 4, event_type: "status_changed", actor: { id: 2, name: "Arjun Agent" }, metadata: { from: "ASSIGNED", to: "IN_PROGRESS" }, created_at: now },
        { id: 5, event_type: "escalated", actor: null, metadata: { reason: "SLA breached", auto: true }, created_at: now },
        { id: 6, event_type: "assigned", actor: { id: 2, name: "Arjun Agent" }, metadata: { assignee: "Arjun Agent", assignee_id: 2 }, created_at: now },
      ],
    };
    mockFetch((u) => (u.includes("/api/v1/tickets/1") ? { body: withHistory } : undefined), signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/tickets/1");
    const timeline = await screen.findByRole("list", { name: "Ticket timeline" });
    expect(timeline).toHaveTextContent("Ada Admin created the ticket via Email");
    expect(timeline).toHaveTextContent("AI triage: Payments related · Critical · 82% confidence");
    expect(timeline).toHaveTextContent("Ada Admin assigned it to Arjun Agent");
    expect(timeline).toHaveTextContent("VIP customer");
    expect(timeline).toHaveTextContent("Arjun Agent moved it from Assigned to In progress");
    expect(timeline).toHaveTextContent("SLA engine escalated the ticket");
    expect(timeline).toHaveTextContent("Arjun Agent took the ticket");
  });
});
