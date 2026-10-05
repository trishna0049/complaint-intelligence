import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { TeamInfo, User } from "@/api/types";
import { adminUser, agentUser, mockFetch, renderRoute, session, signedInAs } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const emptyPage = { items: [], total: 0, page: 1, page_size: 25 };
const authHeader = (init?: RequestInit) => (init?.headers as Record<string, string> | undefined)?.Authorization;

describe("login and session", () => {
  it("anonymous visitors are sent to the login page and come back after signing in", async () => {
    let signedIn = false;
    const fetchMock = mockFetch(
      (u, i) => {
        if (u.endsWith("/auth/refresh")) return signedIn ? { body: session(agentUser) } : { status: 401, body: { detail: { code: "no_refresh_token", message: "x" } } };
        if (u.endsWith("/auth/login") && i?.method === "POST") {
          const body = JSON.parse(String(i.body));
          if (body.password !== "Agent@12345") return { status: 401, body: { detail: { code: "invalid_credentials", message: "Invalid email or password." } } };
          signedIn = true;
          return { body: session(agentUser) };
        }
        return undefined;
      },
      (u, i) => (u.includes("/api/v1/tickets?") ? (authHeader(i) === "Bearer token-2" ? { body: emptyPage } : { status: 401, body: {} }) : undefined),
      signedInAs(null),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets?view=escalated");
    expect(await screen.findByRole("heading", { name: "Complaint Intelligence" })).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Email"), "arjun@shopzilla.example");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");

    await userEvent.clear(screen.getByLabelText("Password"));
    await userEvent.type(screen.getByLabelText("Password"), "Agent@12345");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    // Back on the page they asked for, with the access token attached to API calls.
    expect(await screen.findByRole("heading", { name: "Ticket queue" })).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => String(u).includes("status=ESCALATED") && authHeader(i) === "Bearer token-2")).toBe(true),
    );
  });

  it("an expired access token is refreshed once and the request retried", async () => {
    let refreshes = 0;
    mockFetch(
      (u) => {
        if (!u.endsWith("/auth/refresh")) return undefined;
        refreshes += 1;
        return { body: { ...session(adminUser), access_token: `token-v${refreshes}` } };
      },
      // The first token (from the session restore) is "expired"; only the renewed one works.
      (u, i) => (u.includes("/api/v1/tickets?") ? (authHeader(i) === "Bearer token-v2" ? { body: emptyPage } : { status: 401, body: { detail: { code: "token_expired", message: "expired" } } }) : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets");
    expect(await screen.findByText("No tickets match")).toBeInTheDocument();
    expect(refreshes).toBe(2);
  });

  it("when the session can't be renewed the user is signed out with an explanation", async () => {
    let refreshes = 0;
    mockFetch(
      (u) => {
        if (!u.endsWith("/auth/refresh")) return undefined;
        refreshes += 1;
        return refreshes === 1 ? { body: session(adminUser) } : { status: 401, body: { detail: { code: "refresh_token_reused", message: "ended" } } };
      },
      (u) => (u.includes("/api/v1/tickets?") ? { status: 401, body: {} } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets");
    expect(await screen.findByRole("alert")).toHaveTextContent("Your session has ended. Please sign in again.");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("sign out calls the API and returns to the login page", async () => {
    let signedIn = true;
    const fetchMock = mockFetch(
      (u) => (u.endsWith("/auth/refresh") ? (signedIn ? { body: session(adminUser) } : { status: 401, body: {} }) : undefined),
      (u) => (u.endsWith("/auth/logout") ? ((signedIn = false), { status: 204 }) : undefined),
      (u) => (u.includes("/api/v1/tickets?") ? { body: emptyPage } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets");
    await userEvent.click(await screen.findByRole("button", { name: /Sign out/ }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/auth/logout"))).toBe(true);
  });
});

describe("role-aware navigation", () => {
  it("agents see the ticket workspace but no dashboard or admin links, and land on My work", async () => {
    mockFetch(
      (u) => (u.includes("/api/v1/tickets/summary") ? { body: { by_status: {}, open: 0 } } : undefined),
      (u) => (u.includes("/api/v1/tickets?") ? { body: emptyPage } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/");
    expect(await screen.findByRole("heading", { name: "My work" })).toBeInTheDocument();
    expect(await screen.findByText("Nothing assigned to you")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Ticket queue" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "My work" })).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Dashboard" })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Users" })).toBeNull();
    expect(screen.getByTestId("user-menu")).toHaveTextContent("Payments Support");
  });

  it("agents opening an admin URL get a clear no-access page", async () => {
    mockFetch(signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/admin/users");
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
  });

  it("admins see the admin section", async () => {
    mockFetch(signedInAs(adminUser), () => ({ body: [] }));
    renderRoute(<App />, "/admin/categories");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    for (const name of ["Dashboard", "Users", "Teams", "Categories"]) expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
  });
});

const teams: TeamInfo[] = [
  { id: 3, name: "Payments Support", description: "Owns Payments related tickets", department: { id: 1, name: "Finance Operations" },
    member_count: 56, categories: ["Payments related"] },
  { id: 4, name: "Returns & Pickups", description: null, department: { id: 2, name: "Order Fulfilment" }, member_count: 572,
    categories: ["Returns"] },
];

describe("admin screens", () => {
  it("users: list, then create a user", async () => {
    const created: User = { ...agentUser, id: 9, name: "New Person", email: "new.person@shopzilla.example", source: "app" };
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/api/v1/users") && i?.method === "POST" ? { status: 201, body: created } : undefined),
      (u) => (u.includes("/api/v1/users?") ? { body: { items: [adminUser, agentUser], total: 2, page: 1, page_size: 25 } } : undefined),
      (u) => (u.endsWith("/api/v1/teams") ? { body: teams } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/admin/users");
    const row = (await screen.findByText("Arjun Agent")).closest("tr")!;
    expect(row).toHaveTextContent("Payments Support");
    expect(row).toHaveTextContent("Mason Gupta");

    await userEvent.click(screen.getByRole("button", { name: "New user" }));
    const dialog = screen.getByRole("dialog", { name: "New user" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("valid email");
    await userEvent.type(within(dialog).getByLabelText("Full name"), "New Person");
    await userEvent.type(within(dialog).getByLabelText("Email"), "new.person@shopzilla.example");
    await userEvent.type(within(dialog).getByLabelText("Initial password"), "Sturdy-pass-123");
    await userEvent.selectOptions(within(dialog).getByLabelText("Team"), "3");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const post = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/api/v1/users") && i?.method === "POST")!;
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      name: "New Person", email: "new.person@shopzilla.example", password: "Sturdy-pass-123", role: "AGENT", team_id: 3,
    });
  });

  it("teams: grouped by department with members and owned categories", async () => {
    mockFetch(
      (u) => (u.endsWith("/api/v1/teams") ? { body: teams } : undefined),
      (u) => (u.endsWith("/api/v1/departments") ? { body: [{ id: 1, name: "Finance Operations" }, { id: 2, name: "Order Fulfilment" }] } : undefined),
      signedInAs(adminUser),
    );
    renderRoute(<App />, "/admin/teams");
    expect(await screen.findByText("Finance Operations")).toBeInTheDocument();
    expect(screen.getByText("56 active members")).toBeInTheDocument();
    expect(screen.getByText("Payments related")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete Payments Support" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Move them to another team first.");
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete team" })).toBeDisabled();
  });
});
