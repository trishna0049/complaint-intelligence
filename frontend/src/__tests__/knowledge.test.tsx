import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { Article, ArticleHit, ArticleSummary, SimilarTicket, TicketDetail } from "@/api/types";
import { ticket } from "@/test/fixtures";
import { adminUser, agentUser, mockFetch, renderRoute, signedInAs } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const now = new Date().toISOString();
const bodyOf = (init?: RequestInit) => JSON.parse(String(init?.body ?? "{}"));
const isTicket1 = (u: string) => u.split("?")[0].endsWith("/api/v1/tickets/1");

const similar: SimilarTicket[] = [{
  id: 7, ticket_number: "INC-00007", subject: "Charged two times", snippet: "Money debited two times for one order", status: "CLOSED",
  category: "Payments related", intent: "Online Payment Issues", priority: "High", resolution: "Reversed the duplicate debit",
  csat_score: 4, source: "new", created_at: now, score: 0.03, similarity: 0.81, matched_by: "both",
}];
const summary = (id: number, title: string, category: string | null): ArticleSummary =>
  ({ id, title, category, snippet: `${title} — what to do.`, usage_count: 2, updated_at: now });
const hit = (s: ArticleSummary, similarity: number | null): ArticleHit => ({ ...s, score: 0.02, similarity, matched_by: similarity ? "both" : "keywords" });
const duplicate = summary(1, "Duplicate or double payment for one order", "Payments related");
const refund = summary(3, "Refund policy and timelines", "Refund Related");
const writing = summary(25, "Writing replies to customers", null);
const article: Article = {
  id: 1, title: duplicate.title, body: "Count the successful captures.\n\nRaise a reversal the same day.", category: "Payments related",
  usage_count: 2, updated_by: { id: 1, name: "Ada Admin" }, created_at: now, updated_at: now,
};

describe("retrieval on the ticket page", () => {
  it("shows similar tickets and help articles", async () => {
    mockFetch(
      (u) => (u.includes("/tickets/1/similar") ? { body: similar } : undefined),
      (u) => (u.includes("/knowledge/search") && u.includes("ticket_id=1") ? { body: [hit(duplicate, 0.56)] } : undefined),
      (u) => (isTicket1(u) ? { body: ticket } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    const sims = await screen.findByRole("list", { name: "Similar tickets" });
    expect(sims).toHaveTextContent("INC-00007");
    expect(sims).toHaveTextContent("81% match");
    expect(sims).toHaveTextContent("Resolved: Reversed the duplicate debit");
    expect(within(sims).getByRole("link")).toHaveAttribute("href", "/tickets/7");
    const help = await screen.findByRole("list", { name: "Help articles" });
    expect(within(help).getByRole("link", { name: /Duplicate or double payment/ })).toHaveAttribute("href", "/knowledge/1");
  });

  it("the copilot shows what it was grounded in, highlighting what it used", async () => {
    const t: TicketDetail = {
      ...ticket,
      copilot: {
        id: 5, kind: "copilot", category: "Payments related", intent: null, sentiment: null, priority: "Critical", confidence: 0.8,
        summary: "Customer was charged twice.", root_cause: "Likely a duplicate capture.", key_issues: ["Double charge"],
        recommendations: ["Follow the help article “Duplicate or double payment for one order”"], draft_response: "Hello",
        provider: "mock", model: "mock-copilot-v3", model_version: "triage-v1", prompt_version: "copilot-v3", usage: null,
        draft_status: "pending", reviewed_by: null, reviewed_at: null, final_response: null, edited: null, comment_id: null,
        discard_reason: null, created_at: now,
        grounding: [
          { ref: "A1", type: "article", id: 1, title: duplicate.title, similarity: 0.56, cited: true },
          { ref: "A2", type: "article", id: 2, title: "Money debited but order not placed", similarity: 0.4, cited: false },
          { ref: "T1", type: "ticket", id: 7, title: "Charged two times", ticket_number: "INC-00007", similarity: 0.81, cited: true },
        ],
      },
    };
    mockFetch((u) => (isTicket1(u) ? { body: t } : undefined), signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/tickets/1");
    const sources = await screen.findByRole("region", { name: "Sources" });
    const used = within(sources).getAllByTitle("Used by the copilot");
    expect(used.map((l) => l.textContent)).toEqual([duplicate.title, "INC-00007 · Charged two times"]);
    expect(within(sources).getByTitle("Given to the copilot, not used")).toHaveTextContent("Money debited but order not placed");
    expect(used[1]).toHaveAttribute("href", "/tickets/7");
  });
});

describe("knowledge base", () => {
  it("lists articles by category and searches by meaning", async () => {
    const fetchMock = mockFetch(
      (u) => (u.includes("/knowledge/search") ? { body: [hit(refund, 0.61), hit(writing, null)] } : undefined),
      (u) => (u.includes("/api/v1/knowledge?") ? { body: { items: [duplicate, refund, writing], total: 3, page: 1, page_size: 200 } } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/knowledge");
    expect(await screen.findByRole("region", { name: "Payments related" })).toHaveTextContent(duplicate.title);
    expect(screen.getByRole("region", { name: "General" })).toHaveTextContent("Writing replies to customers");
    expect(screen.queryByRole("button", { name: "New article" })).toBeNull(); // agents read only

    await userEvent.type(screen.getByLabelText("Search the knowledge base"), "refund not credited");
    const results = await screen.findByRole("list", { name: "Search results" });
    expect(results).toHaveTextContent("Refund policy and timelines");
    expect(results).toHaveTextContent("61% match");
    expect(results).toHaveTextContent("keyword match");
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("q=refund+not+credited"))).toBe(true));
  });

  it("admins create an article (validated) and land on it", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/api/v1/knowledge") && i?.method === "POST" ? { status: 201, body: { ...article, id: 30, title: bodyOf(i).title } } : undefined),
      (u) => (u.endsWith("/api/v1/knowledge/30") ? { body: { ...article, id: 30, title: "Gift cards" } } : undefined),
      (u) => (u.includes("/api/v1/knowledge?") ? { body: { items: [], total: 0, page: 1, page_size: 200 } } : undefined),
      (u) => (u.includes("/api/v1/categories") ? { body: [{ name: "Offers & Cashback" }] } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/knowledge");
    await userEvent.click(await screen.findByRole("button", { name: "New article" }));
    const dialog = screen.getByRole("dialog", { name: "New article" });
    await userEvent.type(within(dialog).getByLabelText("Title"), "Gift cards");
    await userEvent.type(within(dialog).getByLabelText("Article"), "Too short");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create article" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("at least 20 characters");
    await userEvent.type(within(dialog).getByLabelText("Article"), " — gift card balances never expire.");
    await userEvent.selectOptions(within(dialog).getByLabelText("Category"), "Offers & Cashback");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create article" }));
    expect(await screen.findByRole("heading", { name: "Gift cards" })).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/knowledge") && i?.method === "POST")!;
    expect(bodyOf(call[1])).toEqual({ title: "Gift cards", body: "Too short — gift card balances never expire.", category: "Offers & Cashback" });
  });

  it("an article shows its paragraphs; admins edit and delete it", async () => {
    let current = article;
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/knowledge/1") && i?.method === "PATCH" ? ((current = { ...current, ...bodyOf(i) }), { body: current }) : undefined),
      (u, i) => (u.endsWith("/knowledge/1") && i?.method === "DELETE" ? { status: 204 } : undefined),
      (u) => (u.endsWith("/api/v1/knowledge/1") ? { body: current } : undefined),
      (u) => (u.includes("/api/v1/knowledge?") ? { body: { items: [], total: 0, page: 1, page_size: 200 } } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/knowledge/1");
    expect(await screen.findByText("Raise a reversal the same day.")).toBeInTheDocument();
    expect(screen.getByText(/cited by the copilot 2×/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog", { name: "Edit article" });
    await userEvent.clear(within(dialog).getByLabelText("Title"));
    await userEvent.type(within(dialog).getByLabelText("Title"), "Double payments");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("heading", { name: "Double payments" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete for good" }));
    expect(await screen.findByRole("heading", { name: "Knowledge base" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/knowledge/1") && i?.method === "DELETE")).toBe(true);
  });

  it("agents can read an article but not change it", async () => {
    mockFetch((u) => (u.endsWith("/api/v1/knowledge/1") ? { body: article } : undefined), signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/knowledge/1");
    expect(await screen.findByRole("heading", { name: article.title })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});
