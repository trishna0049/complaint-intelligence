import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { SlaAnalytics, SlaPolicy, SlaView, TicketDetail } from "@/api/types";
import { SlaBadge } from "@/components/Sla";
import { SlaPanel } from "@/components/SlaPanel";
import { liveState } from "@/lib/sla";
import { ticket } from "@/test/fixtures";
import { adminUser, agentUser, mockFetch, renderRoute, signedInAs } from "@/test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const now = Date.now();
const iso = (ms: number) => new Date(ms).toISOString();
const clock = (patch: Partial<SlaView>): SlaView => ({
  state: "running", deadline: iso(now + 90 * 60_000), remaining_seconds: 5400, ratio: 0.25, target_seconds: 7200, paused: false,
  started_at: iso(now - 30 * 60_000), breached_at: null, warned_at: null, policy: { id: 1, name: "Critical — 2 hours", target_minutes: 120 },
  ...patch,
});

describe("SLA badge", () => {
  it("is green on track, amber from 80 %, red when breached, grey when paused", () => {
    const { rerender } = render(<SlaBadge sla={clock({})} />);
    expect(screen.getByText(/On track · 1h (29|30)m left/)).toBeInTheDocument();
    rerender(<SlaBadge sla={clock({ deadline: iso(now + 20 * 60_000) })} />);
    expect(screen.getByText(/At risk · 1[89]m \d\ds left/)).toBeInTheDocument();
    rerender(<SlaBadge sla={clock({ state: "breached", deadline: iso(now - 12 * 60_000), breached_at: iso(now - 12 * 60_000) })} />);
    expect(screen.getByText(/Breached · 1[12]m \d\ds over/)).toBeInTheDocument();
    rerender(<SlaBadge sla={clock({ state: "paused", paused: true })} />);
    expect(screen.getByText("Paused")).toBeInTheDocument();
    rerender(<SlaBadge sla={clock({ state: "met" })} />);
    expect(screen.getByText("SLA met")).toBeInTheDocument();
    rerender(<SlaBadge sla={clock({ state: "none" })} />);
    expect(screen.queryByText(/SLA|track/)).toBeNull();
  });

  it("crosses into at risk and breached live, without waiting for the server", () => {
    const s = clock({ deadline: iso(now + 25 * 60_000) }); // 25 of 120 minutes left: running
    expect(liveState(s, now).state).toBe("running");
    expect(liveState(s, now + 2 * 60_000).state).toBe("at_risk"); // < 24 min left = 80 % used
    expect(liveState(s, now + 26 * 60_000).state).toBe("breached");
    expect(liveState(clock({ state: "paused", paused: true, deadline: iso(now - 60_000) }), now).state).toBe("paused");
  });
});

describe("SLA on the ticket page and in the queue", () => {
  it("shows the countdown and the SLA card", async () => {
    const t: TicketDetail = { ...ticket, sla: clock({ warned_at: null }) };
    mockFetch((u) => (u.split("?")[0].endsWith("/api/v1/tickets/1") ? { body: t } : undefined), signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/tickets/1");
    expect(await screen.findByText(/On track · 1h (29|30)m left/)).toBeInTheDocument();
    expect(screen.getByText("Critical — 2 hours")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "SLA used" })).toHaveAttribute("aria-valuenow", "25");
  });

  it("refreshes until the SLA worker has stopped the clock of a resolved ticket", async () => {
    let calls = 0;
    const resolved: TicketDetail = { ...ticket, status: "RESOLVED", updated_at: iso(Date.now()), sla: clock({}) };
    mockFetch(
      (u) => (u.split("?")[0].endsWith("/api/v1/tickets/1")
        ? ((calls += 1), { body: calls < 2 ? resolved : { ...resolved, sla: clock({ state: "met" }) } }) : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    expect(await screen.findByText(/On track/)).toBeInTheDocument();
    expect((await screen.findAllByText("SLA met", {}, { timeout: 4000 })).length).toBeGreaterThan(0);
  });

  it("queue views for at-risk and breached SLAs, due soonest first", async () => {
    const fetchMock = mockFetch(
      (u) => (u.includes("/api/v1/tickets?") ? { body: { items: [{ ...ticket, sla: clock({ deadline: iso(now + 10 * 60_000) }) }], total: 1, page: 1, page_size: 25 } } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets");
    await userEvent.click(await screen.findByRole("tab", { name: "SLA at risk" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("sla=at_risk") && String(u).includes("sort=sla"))).toBe(true));
    const row = (await screen.findByText("INC-00001")).closest("tr")!;
    expect(within(row).getByText(/left/)).toBeInTheDocument();
  });
});

const policies: SlaPolicy[] = [
  { id: 1, name: "Critical — 2 hours", priority: "Critical", category: null, target_minutes: 120, is_active: true, created_at: iso(now), updated_at: iso(now) },
  { id: 5, name: "Refund high — 4 hours", priority: "High", category: "Refund Related", target_minutes: 240, is_active: true, created_at: iso(now), updated_at: iso(now) },
];

describe("SLA policies (admin)", () => {
  it("edits a target, creates and deletes a policy; defaults can't be deleted", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/sla-policies/1") && i?.method === "PATCH" ? { body: { ...policies[0], target_minutes: 90 } } : undefined),
      (u, i) => (u.endsWith("/sla-policies/5") && i?.method === "DELETE" ? { status: 204 } : undefined),
      (u, i) => (u.endsWith("/sla-policies") && i?.method === "POST" ? { status: 201, body: { ...policies[1], id: 9 } } : undefined),
      (u) => (u.endsWith("/sla-policies") ? { body: policies } : undefined),
      (u) => (u.includes("/api/v1/categories") ? { body: [{ name: "Refund Related" }] } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/admin/sla");
    const table = await screen.findByRole("table", { name: "SLA policies" });
    expect(within(table).queryByRole("button", { name: "Delete Critical — 2 hours" })).toBeNull();
    const target = within(table).getByLabelText("Target minutes for Critical — 2 hours");
    await userEvent.clear(target);
    await userEvent.type(target, "90");
    await userEvent.click(within(table).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/sla-policies/1") && i?.method === "PATCH")).toBe(true));
    const patch = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/sla-policies/1") && i?.method === "PATCH")!;
    expect(JSON.parse(String(patch[1]?.body))).toEqual({ target_minutes: 90 });

    await userEvent.click(within(table).getByRole("button", { name: "Delete Refund high — 4 hours" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/sla-policies/5") && i?.method === "DELETE")).toBe(true));

    await userEvent.click(screen.getByRole("button", { name: "New policy" }));
    const dialog = screen.getByRole("dialog", { name: "New SLA policy" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Create policy" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Give the policy a name.");
    await userEvent.type(within(dialog).getByLabelText("Name"), "Refund high — 4 hours");
    await userEvent.selectOptions(within(dialog).getByLabelText("Category"), "Refund Related");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create policy" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const post = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/sla-policies") && i?.method === "POST")!;
    expect(JSON.parse(String(post[1]?.body))).toEqual({ name: "Refund high — 4 hours", priority: "High", category: "Refund Related", target_minutes: 240, is_active: true });
  });

  it("is Admin only", async () => {
    mockFetch(signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/admin/sla");
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
  });
});

describe("dashboard SLA panel", () => {
  it("shows the breach rate, what is at risk now and the breakdowns", async () => {
    const sla: SlaAnalytics = {
      window_days: 30, with_sla: 1200, breached: 150, met: 1000, breach_rate: 0.125, avg_resolution_minutes: 95, avg_target_minutes: 600,
      open: { at_risk: 3, breached: 2, paused: 1, running: 20 },
      by_priority: [{ name: "Critical", with_sla: 100, breached: 30, breach_rate: 0.3 }, { name: "Low", with_sla: 500, breached: 10, breach_rate: 0.02 }],
      by_category: [], by_team: [{ name: "Payments Support", with_sla: 300, breached: 60, breach_rate: 0.2 }],
      trend: [],
    };
    mockFetch(
      (u) => (u.includes("/api/v1/analytics/sla") ? { body: sla } : undefined),
      signedInAs(adminUser),
      () => ({ body: {} }),
    );
    renderRoute(<SlaPanel days={30} />);
    expect(await screen.findByText("12.5%")).toBeInTheDocument();
    expect(screen.getByText("150 of 1,200 tickets")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /At risk now\s*3/ })).toHaveAttribute("href", "/tickets?view=sla_risk");
    const byPriority = screen.getByRole("table", { name: "Breach rate by priority" });
    expect(within(byPriority).getByRole("row", { name: /Critical/ })).toHaveTextContent("30.0%");
    expect(screen.getByRole("table", { name: "Breach rate by team (top 6)" })).toHaveTextContent("Payments Support");
  });
});
