// The Pipeline page in a real browser, against the fixture export: the record runs from
// 2026-09-01 to 2026-11-18 (79 days; the export ran on 2026-11-19). 54 mornings a run was due:
// 48 on time, 2 late, 2 held back (09-22, 10-28), 1 failed (10-15), 1 missed (09-30); 25 with
// no run due. Compute $2.841 in all: $0.0526 per daily run, $1.08 a month.
import { expect, test } from "@playwright/test";

test("without JavaScript: the status, the three numbers, the calendar and the table are in the page", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("http://localhost:4173/Earnings-Watch/pipeline/");
  await expect(page.getByTestId("status")).toHaveText(
    "Runs every business-day morning. Complete record since September 1, 2026.",
  );
  await expect(page.getByTestId("on-time")).toHaveText("89%");
  await expect(page.locator(".fig").first()).toContainText("on 48 of 54 mornings a run was due");
  await expect(page.getByTestId("held")).toHaveText("2");
  await expect(page.locator(".fig").nth(1)).toContainText("held back its export twice");
  await expect(page.locator(".fig").nth(1)).toContainText("3 fault drills");
  await expect(page.getByTestId("per-run")).toHaveText("$0.05");
  await expect(page.locator(".fig").nth(2)).toContainText("Costs about $1.08 a month.");
  // One cell per recorded day, each naming its day and state; days outside the record are blank.
  const cells = page.getByTestId("calendar").locator("button");
  await expect(cells).toHaveCount(79);
  await expect(page.locator('[data-day="2026-10-28"]')).toHaveAttribute("title", "Wednesday, October 28, 2026: Held back, exported 13:57 UTC");
  await expect(page.locator('[data-day="2026-10-15"]')).toHaveAttribute("data-state", "failed");
  await expect(page.locator('[data-day="2026-09-08"]')).toHaveAttribute("data-state", "no_run_expected"); // after Labor Day
  await expect(page.getByTestId("day-detail")).toContainText("November 18, 2026: On time, exported 06:08 UTC.");
  await expect(page.getByTestId("days").locator("tbody tr")).toHaveCount(79);
  await expect(page.getByTestId("days").locator("tbody tr").first()).toContainText("2026-11-18");
  await expect(page.getByTestId("events").locator("li")).toHaveCount(6);
  // Nothing relative to today: the page must still read correctly after the pipeline stops.
  await expect(page.locator("main")).not.toContainText(/yesterday|this morning|last 30 days|today/i);
  await context.close();
});

test("pointing at a day, or moving with the arrow keys, shows that day", async ({ page }) => {
  /** @type {string[]} */
  const problems = [];
  page.on("console", (m) => ["error", "warning"].includes(m.type()) && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto("pipeline/");
  await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
  await page.locator('[data-day="2026-09-22"]').hover();
  await expect(page.getByTestId("day-detail")).toContainText("September 22, 2026: Held back, exported 13:57 UTC.");
  // Only one cell is a tab stop; the arrows move a day (up, down) or a week (left, right).
  await page.locator('[data-day="2026-09-22"]').click();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("day-detail")).toContainText("September 23, 2026");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("day-detail")).toContainText("September 30, 2026: Missed.");
  await expect(page.locator('[data-day="2026-09-30"]')).toBeFocused();
  await page.keyboard.press("End");
  await expect(page.getByTestId("day-detail")).toContainText("November 18, 2026");
  await expect(page.getByTestId("calendar").locator('button[tabindex="0"]')).toHaveCount(1);
  expect(problems).toEqual([]);
});

test("on a phone the page fits the screen, and the diagram reads top to bottom", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("pipeline/");
  await expect(page.locator("svg.narrow")).toBeVisible();
  await expect(page.locator("svg.wide")).toBeHidden();
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits).toBe(true);
});

test("the overview's cost is the same average, since the record began", async ({ page }) => {
  await page.goto("");
  const tile = page.locator(".quote").filter({ hasText: "average per daily run" });
  await expect(tile).toContainText("since September 1, 2026");
  await expect(tile.locator(".v")).toHaveText("$0.05");
  await tile.getByRole("link", { name: "what it covers" }).click();
  await expect(page).toHaveURL(/\/pipeline\/#what-it-covers$/);
});
