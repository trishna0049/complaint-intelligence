import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { Analysis, TicketDetail } from "@/api/types";
import { ticket } from "@/test/fixtures";
import { adminUser, agentUser, mockFetch, renderRoute, signedInAs } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const now = new Date().toISOString();
const DRAFT = "Hello,\n\nI'm sorry for the trouble. I'm looking into the duplicate charge now.\n\nRegards,\nShopzilla Support";
const draft: Analysis = {
  id: 5, kind: "copilot", category: "Payments related", intent: "Online Payment Issues", sentiment: "Very Negative", priority: "Critical",
  confidence: 0.82, summary: "Customer reports a payment problem.", root_cause: "Likely a duplicate capture at the payment gateway.",
  key_issues: ["Payment problem"], recommendations: ["Check the payment gateway logs"], draft_response: DRAFT, provider: "mock",
  model: "mock-copilot-v2", model_version: "triage-v1", prompt_version: "copilot-v2", usage: null, draft_status: "pending",
  reviewed_by: null, reviewed_at: null, final_response: null, edited: null, comment_id: null, discard_reason: null, created_at: now,
};
const withDraft = (copilot: Partial<Analysis> = {}, rest: Partial<TicketDetail> = {}): TicketDetail =>
  ({ ...ticket, copilot: { ...draft, ...copilot }, ...rest });
const bodyOf = (init?: RequestInit) => JSON.parse(String(init?.body ?? "{}"));
const arjun = { id: 2, name: "Arjun Agent" };

describe("copilot on the timeline", () => {
  it("names generate, regenerate, accept (edited) and discard", async () => {
    const actor = { id: 2, name: "Arjun Agent" };
    const t = withDraft({}, {
      timeline: [
        ...ticket.timeline,
        { id: 3, event_type: "copilot_generated", actor, metadata: { regenerated: false, model: "gpt-4o-mini", prompt_version: "copilot-v2" }, created_at: now },
        { id: 4, event_type: "copilot_discarded", actor, metadata: { reason: "Too long" }, created_at: now },
        { id: 5, event_type: "copilot_generated", actor, metadata: { regenerated: true }, created_at: now },
        { id: 6, event_type: "copilot_accepted", actor, metadata: { edited: true }, created_at: now },
      ],
    });
    mockFetch((u) => (u.includes("/api/v1/tickets/1") ? { body: t } : undefined), signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/tickets/1");
    const timeline = await screen.findByRole("list", { name: "Ticket timeline" });
    expect(timeline).toHaveTextContent("Arjun Agent ran the AI copilot");
    expect(timeline).toHaveTextContent("gpt-4o-mini · copilot-v2");
    expect(timeline).toHaveTextContent("Arjun Agent discarded the AI draft");
    expect(timeline).toHaveTextContent("Too long");
    expect(timeline).toHaveTextContent("Arjun Agent regenerated the AI draft");
    expect(timeline).toHaveTextContent("Arjun Agent accepted the AI draft after editing it");
  });
});

describe("copilot draft review", () => {
  it("shows the likely root cause as a hypothesis and the draft as an editable reply", async () => {
    mockFetch((u) => (u.includes("/api/v1/tickets/1") ? { body: withDraft() } : undefined), signedInAs(agentUser), () => ({ body: [] }));
    renderRoute(<App />, "/tickets/1");
    expect(await screen.findByText("Likely a duplicate capture at the payment gateway.")).toBeInTheDocument();
    expect(screen.getByText(/a hypothesis, verify before acting/)).toBeInTheDocument();
    expect(screen.getByLabelText("Reply to the customer")).toHaveValue(DRAFT);
    expect(screen.getByText(/Nothing is sent until you accept/)).toBeInTheDocument();
    expect(screen.getByText(/Mock LLM · mock-copilot-v2 · copilot-v2/)).toBeInTheDocument();
  });

  it("accepting as drafted posts the draft text and shows who accepted it", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/ai/drafts/5/accept") && i?.method === "POST"
        ? { body: withDraft({ draft_status: "accepted", reviewed_by: arjun, reviewed_at: now, final_response: bodyOf(i).response, edited: false, comment_id: 9 },
          { comments: [{ id: 9, body: bodyOf(i).response, ai_assisted: true, author: arjun, created_at: now }] }) }
        : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: withDraft() } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: "Accept & post reply" }));
    const done = await screen.findByRole("region", { name: "Accepted reply" });
    expect(done).toHaveTextContent("Accepted by Arjun Agent");
    expect(done).toHaveTextContent("posted as drafted");
    expect(screen.getByText("AI-assisted")).toBeInTheDocument(); // the comment in the conversation
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/accept"))!;
    expect(bodyOf(call[1])).toEqual({ response: DRAFT });
  });

  it("an edited reply is marked as edited and the edited text is posted", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/ai/drafts/5/accept") ? { body: withDraft({ draft_status: "accepted", reviewed_by: arjun, reviewed_at: now, final_response: bodyOf(i).response, edited: true }) } : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: withDraft() } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    const box = await screen.findByLabelText("Reply to the customer");
    await userEvent.clear(box);
    await userEvent.type(box, "Hello Ravi, the reversal of ₹12,500 is raised (ref RV-1182).");
    expect(within(screen.getByRole("region", { name: "Draft reply" })).getByText("Edited")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept edited reply" }));
    expect(await screen.findByText(/edited before posting/)).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/accept"))!;
    expect(bodyOf(call[1])).toEqual({ response: "Hello Ravi, the reversal of ₹12,500 is raised (ref RV-1182)." });
  });

  it("discard asks for an optional reason", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/ai/drafts/5/discard") ? { body: withDraft({ draft_status: "discarded", reviewed_by: arjun, reviewed_at: now, discard_reason: bodyOf(i).reason }) } : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: withDraft() } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: "Discard" }));
    await userEvent.type(screen.getByLabelText("Why discard? (optional)"), "Wrong tone");
    await userEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    const gone = await screen.findByRole("region", { name: "Discarded draft" });
    expect(gone).toHaveTextContent("Draft discarded by Arjun Agent");
    expect(gone).toHaveTextContent("“Wrong tone”");
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/discard"))!;
    expect(bodyOf(call[1])).toEqual({ reason: "Wrong tone" });
  });

  it("regenerating over unsaved edits asks first", async () => {
    const fetchMock = mockFetch(
      (u, i) => (u.endsWith("/ai/draft-response") && i?.method === "POST" ? { status: 201, body: { ...draft, id: 6 } } : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: withDraft() } : undefined),
      signedInAs(adminUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.type(await screen.findByLabelText("Reply to the customer"), " PS: call me.");
    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Regenerating replaces the draft and your edits.");
    await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/draft-response"))).toBe(false);
    expect(screen.getByLabelText("Reply to the customer")).toHaveValue(`${DRAFT} PS: call me.`);

    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    await userEvent.click(screen.getByRole("button", { name: "Regenerate anyway" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/draft-response"))).toBe(true));
  });

  it("a draft that changed meanwhile (409) is reported, not swallowed", async () => {
    mockFetch(
      (u) => (u.endsWith("/ai/drafts/5/accept") ? { status: 409, body: { detail: { code: "draft_not_pending", message: "This draft was replaced by a newer draft." } } } : undefined),
      (u) => (u.includes("/api/v1/tickets/1") ? { body: withDraft() } : undefined),
      signedInAs(agentUser),
      () => ({ body: [] }),
    );
    renderRoute(<App />, "/tickets/1");
    await userEvent.click(await screen.findByRole("button", { name: "Accept & post reply" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This draft was replaced by a newer draft.");
  });
});
