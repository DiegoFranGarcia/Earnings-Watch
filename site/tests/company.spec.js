// The company pages in a real browser, against the fixture export: one page per company the
// screener covers (40), prerendered. Fixture Co 05 and every fifth company restated one
// quarter's net income; Fixture Co 01 to 20 are among the largest restatements; Fixture Co 36's
// figures are implausible; Fixture Co 37 is behind on its filings (latest quarter 2025-12-31).
import { expect, test } from "@playwright/test";

/**
 * @param {import("@playwright/test").Page} page
 * @param {string} path
 */
async function open(page, path) {
  const response = await page.goto(path);
  await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
  return response;
}

test("a company's page: both views, its quarters, history and restatements, cleanly", async ({ page }) => {
  /** @type {string[]} */
  const problems = [];
  page.on("console", (m) => ["error", "warning"].includes(m.type()) && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("response", (r) => r.status() >= 400 && problems.push(`${r.status()} ${r.url()}`));
  const response = await open(page, "company/1000040/");
  expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fixture Co 40");
  await expect(page.locator(".tags .tag.flag")).toHaveText(["Flagged after restatements", "Flagged as first reported"]);
  await expect(page.locator(".snapshot thead th")).toHaveText(["", "After restatements", "As first reported"]);
  await expect(page.getByTestId("quarters").locator("tbody tr")).toHaveCount(12);
  await expect(page.locator("main")).toContainText("1 of its 12 quarters were restated");
  await expect(page.getByTestId("history").locator("tbody tr")).toHaveCount(1);
  await expect(page.locator(".canvas canvas")).toHaveCount(1);
  await expect(page.locator(".tabs a").nth(2)).toHaveAttribute("aria-current", "page");
  expect(problems).toEqual([]);
});

test("without JavaScript, the page holds every figure", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("http://localhost:4173/Earnings-Watch/company/1000005/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fixture Co 05");
  await expect(page.getByTestId("quarters").locator("tbody tr")).toHaveCount(12);
  await expect(page.getByTestId("largest").locator("tbody tr")).toHaveCount(1);
  await expect(page.locator(".snapshot")).toContainText("Growth");
  await context.close();
});

test("implausible figures and late filings are explained on the page", async ({ page }) => {
  await open(page, "company/1000036/");
  await expect(page.getByTestId("implausible")).toContainText("units mistake");
  await open(page, "company/1000037/");
  await expect(page.locator(".tags")).toContainText("Behind on filings");
  await expect(page.getByTestId("quarters").locator("tbody tr")).toHaveCount(9);
});

test("the company index lists the flagged companies, and finds any by name or CIK", async ({ page }) => {
  await open(page, "company/");
  await expect(page.locator(".list li")).toHaveCount(9);
  await page.getByLabel("Find a company").fill("co 37");
  await expect(page.locator(".list li")).toHaveCount(1);
  await expect(page.locator(".list li")).toContainText("Behind on filings");
  await page.getByLabel("Find a company").fill("1000012");
  await page.getByRole("link", { name: "Fixture Co 12" }).click();
  await expect(page).toHaveURL(/\/company\/1000012\/$/);
});

test("a CIK the site does not cover is a 404", async ({ request }) => {
  expect((await request.get("company/999/")).status()).toBe(404);
});
