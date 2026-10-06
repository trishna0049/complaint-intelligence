import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { AppNotification } from "@/api/types";
import { parseEvents } from "@/notifications/stream";
import { agentUser, mockFetch, renderRoute, signedInAs } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const now = new Date().toISOString();
const note = (patch: Partial<AppNotification>): AppNotification => ({
  id: 1, type: "ticket_assigned", title: "INC-00042 assigned to you", message: "Routed to you by the rules: “Charged twice”.",
  ticket_id: 42, severity: "info", read_at: null, created_at: now, ...patch,
});

/** A text/event-stream response that sends `chunks` (one by one) and then stays open. */
function eventStream(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const c of chunks) {
        controller.enqueue(encoder.encode(c));
        await new Promise((r) => setTimeout(r, 20));
      }
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("SSE parsing", () => {
  it("splits events, skips keep-alives and keeps an unfinished event for later", () => {
    const { events, rest } = parseEvents('event: ready\ndata: {"unread": 2}\n\n: keep-alive\n\nevent: notification\ndata: {"id": 7}\n\nevent: unr');
    expect(events).toEqual([{ event: "ready", data: { unread: 2 } }, { event: "notification", data: { id: 7 } }]);
    expect(rest).toBe("event: unr");
    expect(parseEvents("data: line one\ndata: line two\n\n").events).toEqual([{ event: "message", data: "line one\nline two" }]);
  });
});

describe("live notifications", () => {
  it("the bell shows the unread count and a new alert pops up as a toast", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const u = String(input);
      if (u.includes("/notifications/stream")) {
        expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer token-2"); // token in the header
        return eventStream([
          'event: ready\ndata: {"unread": 2}\n\n',
          `event: notification\ndata: ${JSON.stringify(note({ id: 9, type: "sla_breached", severity: "critical", title: "SLA breached: INC-00042", message: "The deadline passed." }))}\n\n`,
        ]);
      }
      const handled = signedInAs(agentUser)(u, init);
      if (handled) return new Response(handled.status === 204 ? null : JSON.stringify(handled.body ?? {}), { status: handled.status ?? 200, headers: { "Content-Type": "application/json" } });
      return new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 25, by_status: {}, open: 0 }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<App />, "/my-work");
    const region = await screen.findByRole("region", { name: "New notifications" }, { timeout: 4000 });
    const toast = within(region).getByRole("status");
    expect(toast).toHaveTextContent("SLA breached: INC-00042");
    expect(within(toast).getByTitle("Critical")).toBeInTheDocument(); // severity has a label, not colour alone
    expect(screen.getByRole("button", { name: "Notifications, 3 unread" })).toBeInTheDocument();
    await userEvent.click(within(toast).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "New notifications" })).toBeNull());
  });

  it("the bell panel lists the latest and marks all read", async () => {
    let unread = true;
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/notifications/read-all") && i?.method === "POST" ? ((unread = false), { body: { marked: 1 } }) : undefined),
      (u) => (u.includes("/api/v1/notifications?") ? { body: { items: [note({ read_at: unread ? null : now })], total: 1, page: 1, page_size: 8, unread: unread ? 1 : 0 } } : undefined),
      signedInAs(agentUser),
      () => ({ body: { items: [], total: 0, page: 1, page_size: 25, by_status: {}, open: 0 } }),
    );
    renderRoute(<App />, "/my-work");
    await userEvent.click(await screen.findByRole("button", { name: /^Notifications/ }));
    const panel = screen.getByRole("dialog", { name: "Notifications" });
    expect(await within(panel).findByText("INC-00042 assigned to you")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: /Mark all read/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/read-all") && i?.method === "POST")).toBe(true));
    expect(within(panel).getByRole("link", { name: "All notifications" })).toHaveAttribute("href", "/notifications");
  });
});

describe("notifications page", () => {
  it("filters unread, marks one read and saves the e-mail preference", async () => {
    const items = [note({}), note({ id: 2, type: "ticket_escalated", severity: "warning", title: "INC-00007 escalated", read_at: now })];
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/notifications/1/read") && i?.method === "POST" ? { body: { ...items[0], read_at: now } } : undefined),
      (u, i) => (u.endsWith("/notifications/preferences") && i?.method === "PUT" ? { body: JSON.parse(String(i.body)) } : undefined),
      (u) => (u.endsWith("/notifications/preferences") ? { body: { email: true } } : undefined),
      (u) => (u.includes("/api/v1/notifications?") && u.includes("unread=true") ? { body: { items: [items[0]], total: 1, page: 1, page_size: 50, unread: 1 } } : undefined),
      (u) => (u.includes("/api/v1/notifications?") ? { body: { items, total: 2, page: 1, page_size: 50, unread: 1 } } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/notifications");
    const list = await screen.findByRole("list", { name: "Notifications list" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    await userEvent.click(screen.getByRole("tab", { name: /Unread/ }));
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Notifications list" })).getAllByRole("listitem")).toHaveLength(1));
    await userEvent.click(screen.getByRole("button", { name: "Mark read" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/notifications/1/read") && i?.method === "POST")).toBe(true));

    const box = screen.getByLabelText("Also e-mail me escalations and SLA alerts");
    await waitFor(() => expect(box).toBeEnabled());
    await userEvent.click(box);
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/preferences") && i?.method === "PUT")).toBe(true));
    const put = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/preferences") && i?.method === "PUT")!;
    expect(JSON.parse(String(put[1]?.body))).toEqual({ email: false });
  });
});
