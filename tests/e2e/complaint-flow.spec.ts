/**
 * The core user flow: dashboard → new complaint → AI triage preview → save → LLM insights →
 * find it in the list and on the dashboard → resolve it.
 */
import { expect, test } from "@playwright/test";

test("complaint is triaged, summarised, tracked on the dashboard and resolved", async ({ page }) => {
  const subject = `E2E charged twice ${Date.now()}`;
  const nav = (name: string) => page.getByRole("navigation").getByRole("link", { name, exact: true });

  // 1. Dashboard loads (empty state on a fresh e2e database, charts otherwise).
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Complaint dashboard" })).toBeVisible();
  await expect(page.getByText(/triage-v1/)).toBeVisible(); // trained classifier is loaded

  // 2. New complaint: fill the spec's example and preview the AI triage before saving.
  await nav("New complaint").click();
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
  await page.getByRole("button", { name: "Save complaint" }).click();
  await expect(page).toHaveURL(/\/complaints\/\d+$/);
  const complaintUrl = page.url();
  await expect(page.getByRole("heading", { name: subject })).toBeVisible();
  await expect(page.getByText("Very negative sentiment")).toBeVisible();
  await expect(page.getByText("already Critical").first()).toBeVisible();

  // 4. LLM insights (mock provider): summary, key issues, recommended actions, draft reply.
  await page.getByRole("button", { name: "Generate insights" }).click();
  await expect(page.getByRole("heading", { name: "Recommended actions" })).toBeVisible();
  await expect(page.getByText(/^Customer reports a payment problem/)).toBeVisible();
  await expect(page.getByText(/Mock LLM · mock-insight-v1 · insight-v1/)).toBeVisible();
  await expect(page.getByText("Amount involved: ₹12,500")).toBeVisible();
  await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible();

  // 5. Complaints list: search finds it with its triage columns.
  await nav("Complaints").click();
  await page.getByLabel("Search complaints").fill(subject);
  const row = page.getByRole("row", { name: new RegExp(subject) });
  await expect(row).toBeVisible();
  await expect(row).toContainText("Payments related");
  await expect(row).toContainText("Very Negative");
  await expect(row).toContainText("Critical");
  await expect(row).toContainText("Open");

  // 6. Dashboard: it appears among the open high-priority complaints.
  await nav("Dashboard").click();
  const hot = page.locator("div.rounded-lg", { has: page.getByText("Open high-priority complaints") });
  await expect(hot.getByText(subject)).toBeVisible();

  // 7. Resolve it: status updates and it leaves the open high-priority list.
  await page.goto(complaintUrl);
  await page.getByLabel("Status").selectOption("Resolved");
  await expect(page.getByLabel("Status")).toHaveValue("Resolved");
  await expect(page.locator("dt", { hasText: "Resolved" }).locator("xpath=following-sibling::dd")).not.toHaveText("—");

  await nav("Dashboard").click();
  await expect(page.getByText("Complaint volume")).toBeVisible(); // dashboard data has rendered
  await expect(hot.getByText(subject)).toHaveCount(0);
});
