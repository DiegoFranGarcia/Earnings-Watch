// The screener in a real browser, against the fixture export: 40 companies in each view, 39 up
// to date with their filings (Fixture Co 37 is behind); 9 flagged after restatements (Fixture
// Co 04, 12, 16, 20, 24, 28, 32, 36, 40), 10 as first reported (Fixture Co 08 too). Every
// company's net income rose by 6.3% of its assets, except Fixture Co 36's (55%: its figures are
// implausible, net income above twice its assets).
import { expect, test } from "@playwright/test";

const URL = "screener/";

/**
 * Open the screener and wait until every row has loaded.
 * @param {import("@playwright/test").Page} page
 */
async function open(page, search = "") {
  await page.goto(URL + search);
  await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
  await expect(page.locator(".tablewrap")).toHaveAttribute("data-rows", "all");
}

const count = (/** @type {import("@playwright/test").Page} */ page) => page.getByTestId("count");
const names = (/** @type {import("@playwright/test").Page} */ page) => page.locator("tbody .co");

test("without JavaScript, the first rows are in the page: flagged first, largest gap in dollars first", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto(`http://localhost:4173/Earnings-Watch/${URL}`);
  await expect(page.locator("tbody tr")).toHaveCount(39);
  await expect(names(page).first()).toHaveText("Fixture Co 40");
  await expect(names(page).nth(1)).toHaveText("Fixture Co 04");
  await expect(names(page).nth(9)).toHaveText("Fixture Co 08");
  await expect(count(page)).toContainText("The first 39 of 39 companies");
  await context.close();
});

test("every row loads, cleanly, from the export's Parquet", async ({ page }) => {
  /** @type {string[]} */
  const problems = [];
  page.on("console", (m) => ["error", "warning"].includes(m.type()) && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  const parquet = page.waitForResponse((r) => r.url().endsWith("/Earnings-Watch/data/export_screener.parquet"));
  await open(page);
  expect((await parquet).status()).toBe(200);
  await expect(count(page)).toHaveText("39 of 39 companies");
  await expect(page.locator(".scatter canvas")).toHaveCount(1);
  expect(problems).toEqual([]);
});

test("filters combine, and the address keeps them for a reload or a shared link", async ({ page }) => {
  await open(page);
  await page.getByLabel("Flagged only").check();
  await expect(count(page)).toHaveText("9 of 39 companies");
  await page.getByLabel("Industry").selectOption("Technology");
  await expect(count(page)).toHaveText("2 of 39 companies");
  await expect(page).toHaveURL(/\?industry=Technology&flagged=1$/);
  await page.reload();
  await expect(page.locator(".tablewrap")).toHaveAttribute("data-rows", "all");
  await expect(count(page)).toHaveText("2 of 39 companies");
  await expect(page.getByLabel("Industry")).toHaveValue("Technology");
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(count(page)).toHaveText("39 of 39 companies");
  await expect(page).toHaveURL(/\/screener\/$/);
});

test("search by name or CIK, and the filer size filter", async ({ page }) => {
  await open(page);
  await page.getByLabel("Search a company").fill("fixture co 1");
  await expect(count(page)).toHaveText("10 of 39 companies");
  await page.getByLabel("Search a company").fill("1000007");
  await expect(names(page)).toHaveText(["Fixture Co 07"]);
  await page.getByLabel("Search a company").fill("");
  await page.getByLabel("Filer size").selectOption("large_accelerated");
  await expect(count(page)).toHaveText("13 of 39 companies");
  await page.getByLabel("Search a company").fill("nothing like this");
  await expect(page.locator("tbody")).toContainText("No company matches");
});

test("the view toggle switches to the figures as first reported", async ({ page }) => {
  await open(page, "?flagged=1");
  await expect(count(page)).toHaveText("9 of 39 companies");
  await page.getByRole("button", { name: "As first reported" }).click();
  await expect(count(page)).toHaveText("10 of 39 companies");
  await expect(page).toHaveURL(/\?view=first_reported&flagged=1$/);
});

test("headers sort, and say how", async ({ page }) => {
  await open(page);
  const company = page.getByRole("columnheader", { name: "Company" });
  await company.getByRole("button").click();
  await expect(company).toHaveAttribute("aria-sort", "ascending");
  await expect(names(page).first()).toHaveText("Fixture Co 01");
  await company.getByRole("button").click();
  await expect(company).toHaveAttribute("aria-sort", "descending");
  await expect(names(page).first()).toHaveText("Fixture Co 40");
  await expect(page).toHaveURL(/\?sort=name&dir=desc$/);
});

test("rows come a page at a time", async ({ page }) => {
  await open(page);
  // 39 rows fit in one page of 100: no button.
  await expect(page.locator("tbody tr")).toHaveCount(39);
  await expect(page.getByRole("button", { name: /^Show/ })).toHaveCount(0);
});

test("dragging across the chart keeps the companies in that area", async ({ page }) => {
  await open(page);
  // The grid: 60px from the left (start well inside it, clear of the axes), 16 from the right
  // and top, 44 from the bottom; the gap runs from -100% (bottom) to +100% (top). Drag from the
  // top down to a gap of 8%, across the width: every flagged company (gaps 12% to 21%) and no
  // other (2% to 6%).
  await expect(page.locator(".scatter")).toHaveAttribute("data-chart", "ready");
  const box = /** @type {{ x: number, y: number, width: number, height: number }} */ (await page.locator(".scatter .canvas").boundingBox());
  const top = box.y + 16;
  const plot = box.height - 16 - 44;
  const at8 = top + ((1 - 0.08) / 2) * plot;
  await page.mouse.move(box.x + 90, top + 12);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, at8 - 20, { steps: 5 });
  await page.mouse.move(box.x + box.width - 18, at8, { steps: 5 });
  await page.mouse.up();
  await expect(count(page)).toHaveText("9 of 39 companies, in the selected area");
  await expect(page).toHaveURL(/[?&]gap=/);
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(count(page)).toHaveText("39 of 39 companies");
});

test("an area in the address is applied, and its companies are those in it", async ({ page }) => {
  await open(page, "?gap=0.1,1");
  await expect(count(page)).toHaveText("9 of 39 companies, in the selected area");
  await open(page, "?change=0.5,1");
  await expect(names(page)).toHaveText(["Fixture Co 36"]);
});

test("on a phone, each company is a card with labeled figures", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await open(page);
  const card = page.locator("tbody tr").first();
  expect(await card.evaluate((el) => getComputedStyle(el).display)).toBe("block");
  await expect(card.locator('td[data-label="Gap / assets"]')).toBeVisible();
  await page.getByLabel("Sort by").selectOption("name asc");
  await expect(names(page).first()).toHaveText("Fixture Co 01");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await context.close();
});

test("companies behind on filings are left out, until asked for", async ({ page }) => {
  await open(page);
  await expect(page.locator("tbody")).not.toContainText("Fixture Co 37");
  await page.getByLabel("Include 1 behind on filings").check();
  await expect(count(page)).toHaveText("40 of 40 companies");
  await expect(page).toHaveURL(/\?behind=1$/);
  const row = page.locator("tbody tr", { hasText: "Fixture Co 37" });
  await expect(row.locator(".tag")).toHaveText("Behind on filings");
  await expect(row.locator('td[data-label="Latest quarter"]')).toHaveText("2025-12-31filed 2026-02-26");
});

test("implausible figures carry a warning, and each row its latest quarter and filing date", async ({ page }) => {
  await open(page);
  const row = page.locator("tbody tr", { hasText: "Fixture Co 36" });
  await expect(row.locator(".tag.check")).toHaveText("Check filing");
  await expect(page.locator("tbody .tag.check")).toHaveCount(1);
  await expect(page.locator('tbody td[data-label="Latest quarter"]').first()).toHaveText("2026-09-30filed 2026-11-02");
});

test("each company links to its own page", async ({ page }) => {
  await open(page);
  await names(page).first().click();
  await expect(page).toHaveURL(/\/Earnings-Watch\/company\/1000040\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fixture Co 40");
});
