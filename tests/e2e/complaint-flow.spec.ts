/**
 * The core user flow: dashboard → create ticket → AI triage preview → save → AI copilot →
 * find it in the ticket list and on the dashboard → assign → start → comment + attachment → resolve → close,
 * with every step on the ticket timeline.
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

  // 4. AI copilot (mock provider): summary, key issues, recommended actions, draft reply.
  await page.getByRole("button", { name: "Run copilot" }).click();
  await expect(page.getByRole("heading", { name: "Recommended actions" })).toBeVisible();
  await expect(page.getByText(/^Customer reports a payment problem/)).toBeVisible();
  await expect(page.getByText(/Mock LLM · mock-insight-v1 · insight-v1/)).toBeVisible();
  await expect(page.getByText("Amount involved: ₹12,500")).toBeVisible();
  await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible();

  // 5. Ticket list: search finds it with its triage columns.
  await nav("Ticket queue").click();
  await page.getByLabel("Search tickets").fill(subject);
  const row = page.getByRole("row", { name: new RegExp(subject) });
  await expect(row).toBeVisible();
  await expect(row).toContainText("Payments related");
  await expect(row).toContainText("Very Negative");
  await expect(row).toContainText("Critical");
  await expect(row).toContainText("Triaged");
  await expect(row).toContainText("Unassigned");

  // 6. Dashboard: it appears among the open high-priority tickets.
  await nav("Dashboard").click();
  const hot = page.locator("div.rounded-lg", { has: page.getByText("Open high-priority tickets") });
  await expect(hot.getByText(subject)).toBeVisible();

  // 7. Work it through the lifecycle from the ticket workspace.
  await page.goto(ticketUrl);
  const actions = page.getByRole("toolbar", { name: "Ticket actions" });
  await expect(actions.getByRole("button", { name: "Close" })).toHaveCount(0); // not allowed from TRIAGED

  await actions.getByRole("button", { name: "Assign" }).click();
  const assign = page.getByRole("dialog", { name: /^Assign INC-/ });
  await assign.getByLabel("Team").selectOption({ label: "Payments Support" });
  const agents = assign.getByRole("radiogroup", { name: "Agent" });
  await expect(agents.getByText("Least busy")).toBeVisible();
  await agents.getByRole("radio").first().check();
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

  const timeline = page.getByRole("list", { name: "Ticket timeline" });
  for (const text of ["created the ticket", "AI triage: Payments related", "assigned it to", "to In progress", "commented",
    "attached statement.txt", "to Resolved", "to Closed"]) {
    await expect(timeline).toContainText(text);
  }

  // 8. It has left the open high-priority list on the dashboard.
  await nav("Dashboard").click();
  await expect(page.getByText("Ticket volume")).toBeVisible(); // dashboard data has rendered
  await expect(hot.getByText(subject)).toHaveCount(0);
});
