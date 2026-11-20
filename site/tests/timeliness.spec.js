// The filing-timeliness page in a real browser, against the fixture export. 10-Ks for 2025:
// 98% of large accelerated filers' by the deadline (60 days), 92% of accelerated (75), 76% of
// non-accelerated (90; 576 of 4,000 within an extension, 384 late). Period years 2009 to 2026,
// 2026 to date (the fixture's export ran on 2026-11-19).
import { expect, test } from "@playwright/test";

test("without JavaScript: the gap first, the chart, the split and the timing in the page", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("http://localhost:4173/Earnings-Watch/timeliness/");
  await expect(page.getByTestId("large")).toHaveText("98%");
  await expect(page.getByTestId("small")).toHaveText("76%");
  await expect(page.locator(".of")).toContainText("periods ending in 2025");
  await expect(page.getByTestId("deadlines")).toContainText("90 days after the year ends to the largest companies' 60");
  await expect(page.getByTestId("deadlines")).toContainText("Accelerated filers, due in 75 days: 92%.");
  // A solid line per group, and a dashed one into 2026, which is not all due yet.
  await expect(page.locator(".chart path.line:not(.open)")).toHaveCount(3);
  await expect(page.locator(".chart path.open")).toHaveCount(3);
  await expect(page.getByTestId("years").locator("tbody tr")).toHaveCount(18);
  await expect(page.getByTestId("years").locator("tbody tr").first()).toContainText("2026 (to date)");
  await expect(page.getByTestId("split-year")).toHaveText("10-Ks for periods ending in 2025");
  await expect(page.getByTestId("split").locator("li").last()).toContainText("76.0% by the deadline, 14.4% within an extension, 9.6% late.");
  await expect(page.getByTestId("timing").locator("tbody tr").first()).toContainText("60 days, +15 with a notice");
  await expect(page.getByTestId("awaiting")).toHaveCount(0);
  await context.close();
});

test("the 10-Q toggle redraws everything for quarterly reports, and keeps it in the address", async ({ page }) => {
  /** @type {string[]} */
  const problems = [];
  page.on("console", (m) => ["error", "warning"].includes(m.type()) && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto("timeliness/");
  await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
  await page.getByRole("button", { name: "10-Q (quarterly)" }).click();
  await expect(page).toHaveURL(/\?form=10-Q$/);
  await expect(page.getByRole("heading", { level: 2 }).first()).toHaveText("10-Qs filed by the deadline, each year");
  await expect(page.getByTestId("timing").locator("tbody tr").last()).toContainText("45 days, +5 with a notice");
  // The opening stays on 10-Ks.
  await expect(page.getByTestId("small")).toHaveText("76%");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
  await expect(page.getByRole("button", { name: "10-Q (quarterly)" })).toHaveAttribute("aria-pressed", "true");
  expect(problems).toEqual([]);
});

test("on a phone: a key above the chart instead of labels, and the timing as cards", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await page.goto("http://localhost:4173/Earnings-Watch/timeliness/");
  await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
  await expect(page.locator(".key").first()).toBeVisible();
  await expect(page.locator(".chart text.label")).toHaveCount(0);
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(390);
  await context.close();
});
