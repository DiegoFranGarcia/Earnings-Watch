// The restatements page in a real browser, against the fixture export. Net income in 2025: 60
// figures amended, 540 changed in a later filing (so 10% amended), at 50 and 400 companies, of
// 4,000 reporting it; the median amendment after 98 days. The table: 15 net income changes
// (Fixture Co 01 to 10 amended in 2025, largest first; Co 21 to 25 small amendments that rank
// against assets), 10 revenue changes in 2024, and one company the screener does not cover.
import { expect, test } from "@playwright/test";

/**
 * @param {import("@playwright/test").Page} page
 */
async function open(page, search = "") {
  await page.goto(`restatements/${search}`);
  await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
  await expect(page.locator(".tablewrap[data-rows]")).toHaveAttribute("data-rows", "all");
}

const count = (/** @type {import("@playwright/test").Page} */ page) => page.getByTestId("count");
const names = (/** @type {import("@playwright/test").Page} */ page) => page.getByTestId("largest").locator("tbody .co");

test("without JavaScript: the finding first, the years and the largest changes in the page", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("http://localhost:4173/Earnings-Watch/restatements/");
  await expect(page.getByTestId("share")).toHaveText("10%");
  await expect(page.locator(".of")).toContainText("in 2025 came in an amendment");
  await expect(page.getByTestId("companies")).toHaveText("450");
  await expect(page.locator(".def")).toContainText("of 4,000 reporting one that year");
  await expect(page.locator(".def")).toContainText("98 days");
  await expect(page.getByTestId("years").locator("tbody tr")).toHaveCount(18);
  await expect(page.getByTestId("largest").locator("tbody tr")).toHaveCount(15);
  await expect(names(page).first()).toHaveText("Fixture Co 01");
  await context.close();
});

test("the table loads cleanly, filters by kind, and orders by dollars, assets or date", async ({ page }) => {
  /** @type {string[]} */
  const problems = [];
  page.on("console", (m) => ["error", "warning"].includes(m.type()) && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await open(page);
  await expect(count(page)).toHaveText("15 changes");
  await expect(page.locator(".chart")).toHaveAttribute("data-chart", "ready");
  await page.getByRole("button", { name: "Changed in a later filing" }).first().click();
  await expect(page.getByTestId("largest")).toContainText("No change of this kind");
  await page.getByRole("button", { name: "Amended only" }).click();
  await expect(count(page)).toHaveText("15 changes");
  await page.getByLabel("Order").selectOption("share");
  await expect(names(page).first()).toHaveText("Fixture Co 21");
  await expect(page).toHaveURL(/\?kind=correction&order=share$/);
  expect(problems).toEqual([]);
});

test("each figure has its own chart and table; companies without a page link to EDGAR", async ({ page }) => {
  await open(page, "?metric=revenue");
  await expect(count(page)).toHaveText("10 changes");
  await expect(page.getByRole("heading", { level: 2 }).first()).toHaveText("Companies that changed revenue they had reported, each year");
  await page.getByRole("button", { name: "Operating cash flow" }).click();
  await expect(names(page)).toHaveText(["Gone Co"]);
  await expect(names(page).first()).toHaveAttribute("href", /sec\.gov/);
  await page.getByRole("button", { name: "Net income" }).click();
  await expect(names(page).first()).toHaveAttribute("href", "/Earnings-Watch/company/1000001/");
});

test("a year from the address, or clicked on the chart, filters the table", async ({ page }) => {
  await open(page, "?year=2025");
  await expect(count(page)).toHaveText("15 changes first seen in 2025");
  await page.getByRole("button", { name: "2025 only: show every year" }).click();
  await expect(count(page)).toHaveText("15 changes");
  await open(page, "?metric=revenue");
  await expect(page.locator(".chart")).toHaveAttribute("data-chart", "ready");
  // Click 2024's bar: 18 years across the grid (56px from the left, 16 from the right), near
  // the bottom of the plot, where every bar is.
  // Centred in the window: the page's navigation is fixed along the bottom.
  await page.locator(".chart .canvas").evaluate((e) => e.scrollIntoView({ block: "center" }));
  const box = /** @type {{ x: number, y: number, width: number, height: number }} */ (await page.locator(".chart .canvas").boundingBox());
  const slot = (box.width - 8 - 56 - 16) / 18;
  await page.mouse.click(box.x + 4 + 56 + slot * (2024 - 2009 + 0.5), box.y + box.height - 28 - 6);
  await expect(count(page)).toHaveText("10 changes first seen in 2024");
  await expect(page).toHaveURL(/year=2024/);
});

test("tag switches are out by default, and in when asked for", async ({ page }) => {
  await open(page);
  await expect(page.getByRole("button", { name: "Tag switch" })).toHaveCount(0);
  await page.getByLabel("Include tag switches").check();
  await expect(page.getByRole("button", { name: "Tag switch" })).toHaveCount(1);
  await expect(page).toHaveURL(/\?tags=1$/);
  await page.getByRole("button", { name: "Count" }).click();
  await expect(page).toHaveURL(/\?tags=1&counts=1$/);
});
