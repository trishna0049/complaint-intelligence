/**
 * The core user flow: dashboard → create ticket → AI triage preview → save → AI copilot →
 * routed by the rules to a Payments Support agent → find it in the ticket list and on the dashboard → reassign →
 * start → comment + attachment → resolve → close, with every step on the ticket timeline.
 */
import { expect, test } from "@playwright/test";

test("ticket is triaged, summarised, tracked on the dashboard and resolved", async ({ page }) => {
  const subject = `E2E charged twice ${Date.now()}`;
  const nav = (name: string) => page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true });

  // 0. Sign in as the seeded admin (scripts/seed.py).
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email").fill("admin@shopzilla.example");
  await page.getByLabel("Password").fill("Admin@12345");
  await page.getByRole("button", { name: "Sign in" }).click();

  // 1. Dashboard loads (empty state on a fresh e2e database, charts otherwise).
  await expect(page.getByRole("heading", { name: "Complaint dashboard" })).toBeVisible();
  await expect(page.getByText(/triage-v1/)).toBeVisible(); // trained classifier is loaded

  // 2. New complaint: fill the spec's example and preview the AI triage before saving.
  await nav("Create ticket").click();
  await page.getByRole("button", { name: "Fill example" }).click();
  await page.getByLabel("Subject (optional)").fill(subject);
  await page.getByRole("button", { name: "Analyze" }).click();

  const preview = page.locator("div.rounded-lg", { has: page.getByText("AI triage preview") });
  await expect(preview.getByText("Why Critical?")).toBeVisible();
  await expect(preview.getByText("Payments related", { exact: true })).toBeVisible();
  await expect(preview.getByText("Very Negative", { exact: true })).toBeVisible();
  await expect(preview.getByText("₹12,500", { exact: true })).toBeVisible();
  await expect(preview.getByText("Repeat contact", { exact: true })).toBeVisible();

  // 3. Save: the detail page shows the stored triage with every priority rule that matched.
  await page.getByRole("button", { name: "Create ticket" }).click();
  await expect(page).toHaveURL(/\/tickets\/\d+$/);
  const ticketUrl = page.url();
  await expect(page.getByRole("heading", { name: subject })).toBeVisible();
  await expect(page.getByText("Very negative sentiment")).toBeVisible();
  await expect(page.getByText("already Critical").first()).toBeVisible();

  // 3b. Routed by the rules (never the LLM): Payments related → Payments Support → least-busy agent.
  const timeline = page.getByRole("list", { name: "Ticket timeline" });
  await expect(timeline).toContainText("Routing rules: assigned to");
  await expect(timeline).toContainText("in Payments Support");
  await expect(page.getByText(/Least busy of \d+ available agents in Payments Support/).first()).toBeVisible();

  // 3c. Retrieval: the seeded knowledge base (MiniLM + full text) offers the duplicate-payment article.
  const help = page.getByRole("list", { name: "Help articles" });
  await expect(help.getByRole("link").first()).toContainText("Duplicate or double payment for one order");

  // 4. AI copilot (mock provider): summary, key issues, recommended actions, draft reply — grounded in the KB.
  await page.getByRole("button", { name: "Run copilot" }).click();
  await expect(page.getByRole("heading", { name: "Recommended actions" })).toBeVisible();
  await expect(page.getByText(/^Customer reports a payment problem/)).toBeVisible();
  await expect(page.getByText(/Mock LLM · mock-copilot-v3 · copilot-v3/)).toBeVisible();
  await expect(page.getByText("Amount involved: ₹12,500")).toBeVisible();
  await expect(page.getByText(/^Likely a duplicate capture at the payment gateway/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible();
  const sources = page.getByRole("region", { name: "Sources" });
  await expect(sources.getByTitle("Used by the copilot").first()).toContainText("Duplicate or double payment for one order");

  // 4b. Human in the loop: nothing is posted until the agent accepts; here they edit the draft first.
  await expect(page.getByText("No comments yet")).toBeVisible();
  const reply = page.getByLabel("Reply to the customer");
  await reply.fill("Hello, we confirmed the duplicate debit of ₹12,500 and are reversing it today.");
  await page.getByRole("button", { name: "Accept edited reply" }).click();
  await expect(page.getByRole("region", { name: "Accepted reply" })).toContainText("edited before posting");
  await expect(page.getByText("AI-assisted")).toBeVisible();

  // 5. Ticket list: search finds it with its triage columns.
  await nav("Ticket queue").click();
  await page.getByLabel("Search tickets").fill(subject);
  const row = page.getByRole("row", { name: new RegExp(subject) });
  await expect(row).toBeVisible();
  await expect(row).toContainText("Payments related");
  await expect(row).toContainText("Very Negative");
  await expect(row).toContainText("Critical");
  await expect(row).toContainText("Assigned");
  await expect(row).toContainText("Payments Support");

  // 5b. Knowledge base: search by meaning.
  await nav("Knowledge base").click();
  await page.getByLabel("Search the knowledge base").fill("when will my refund reach my card");
  await expect(page.getByRole("list", { name: "Search results" }).getByRole("link").first()).toContainText("Refund");

  // 6. Dashboard: it appears among the open high-priority tickets.
  await nav("Dashboard").click();
  const hot = page.locator("div.rounded-lg", { has: page.getByText("Open high-priority tickets") });
  await expect(hot.getByText(subject)).toBeVisible();

  // 7. Work it through the lifecycle from the ticket workspace.
  await page.goto(ticketUrl);
  const actions = page.getByRole("toolbar", { name: "Ticket actions" });
  await expect(actions.getByRole("button", { name: "Close" })).toHaveCount(0); // not allowed from ASSIGNED

  // Reassign by hand to the teammate (the routed agent is marked "Current").
  await actions.getByRole("button", { name: "Assign" }).click();
  const assign = page.getByRole("dialog", { name: /^Assign INC-/ });
  await expect(assign.getByLabel("Team")).toHaveValue(/\d+/); // preselected: the ticket's team
  const agents = assign.getByRole("radiogroup", { name: "Agent" });
  await expect(agents.getByText("Current")).toBeVisible();
  await agents.locator("label", { hasNot: page.getByText("Current") }).first().getByRole("radio").check();
  await assign.getByLabel("Note (optional)").fill("Duplicate debit, high value");
  await assign.getByRole("button", { name: "Assign" }).click();
  await expect(assign).toBeHidden();
  await expect(page.getByText("Assigned", { exact: true }).first()).toBeVisible();

  await actions.getByRole("button", { name: "Start work" }).click();
  await expect(actions.getByRole("button", { name: "Wait on customer" })).toBeVisible();

  await page.getByLabel("Add a comment").fill("Confirmed the duplicate debit with the gateway.");
  await page.getByRole("button", { name: "Add comment" }).click();
  await expect(page.getByText("Confirmed the duplicate debit with the gateway.")).toBeVisible();
  await page.getByLabel("Attach a file").setInputFiles({ name: "statement.txt", mimeType: "text/plain", buffer: Buffer.from("txn 1 and txn 2") });
  await expect(page.getByRole("button", { name: /statement\.txt/ })).toBeVisible();

  await actions.getByRole("button", { name: "Resolve" }).click();
  const resolve = page.getByRole("dialog", { name: /^Resolve INC-/ });
  await resolve.getByLabel("Resolution").fill("Reversed the duplicate ₹12,500 debit.");
  await resolve.getByRole("button", { name: "Resolve" }).click();
  await expect(resolve).toBeHidden();
  await expect(page.getByText("Reversed the duplicate ₹12,500 debit.").first()).toBeVisible();
  await actions.getByRole("button", { name: "Close" }).click();
  await expect(actions.getByRole("button", { name: "Reopen" })).toBeVisible();

  for (const text of ["created the ticket", "AI triage: Payments related", "Routing rules: assigned to", "ran the AI copilot",
    "accepted the AI draft after editing it", "assigned it to",
    "to In progress", "commented",
    "attached statement.txt", "to Resolved", "to Closed"]) {
    await expect(timeline).toContainText(text);
  }

  // 8. It has left the open high-priority list on the dashboard.
  await nav("Dashboard").click();
  await expect(page.getByText("Ticket volume")).toBeVisible(); // dashboard data has rendered
  await expect(hot.getByText(subject)).toHaveCount(0);
});
