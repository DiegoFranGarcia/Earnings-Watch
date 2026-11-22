// What a visitor gets, checked in a real browser against the fixture export (40 invented
// companies: 10 flagged as first reported, 9 after restatements).
import { expect, test } from "@playwright/test";

const PAGES = ["", "screener/", "company/", "restatements/", "timeliness/", "pipeline/", "sql/"];

/**
 * Open a page and wait until it is interactive (the layout sets data-ready once hydrated).
 * @param {import("@playwright/test").Page} page
 */
async function open(page, path = "") {
  const response = await page.goto(path);
  await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
  return response;
}

/**
 * Fail on anything a visitor should never see: errors, warnings, broken requests, third parties.
 * @param {import("@playwright/test").Page} page
 */
function watch(page) {
  /** @type {string[]} */
  const problems = [];
  page.on("console", (m) => ["error", "warning"].includes(m.type()) && problems.push(`console ${m.type()}: ${m.text()}`));
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("response", (r) => r.status() >= 400 && problems.push(`${r.status()} ${r.url()}`));
  page.on("request", (r) => !r.url().startsWith("http://localhost:4173/Earnings-Watch/") && problems.push(`left the site: ${r.url()}`));
  return problems;
}

test("every page loads under the base path, cleanly, with its tab marked current", async ({ page }) => {
  const problems = watch(page);
  for (const [i, path] of PAGES.entries()) {
    const response = await open(page, path);
    expect(response?.status(), path).toBe(200);
    await expect(page.locator(".tabs a").nth(i)).toHaveAttribute("aria-current", "page");
    await expect(page.locator('meta[http-equiv="content-security-policy"]')).toHaveCount(1);
  }
  expect(problems).toEqual([]);
});

test("the dbt docs and the data sit beside the app, under the same base path", async ({ page, request }) => {
  await open(page);
  const docs = page.getByRole("link", { name: "dbt docs" });
  await expect(docs).toHaveAttribute("href", "/Earnings-Watch/dbt-docs/");
  await docs.click();
  await expect(page).toHaveTitle("dbt docs (fixture)");
  for (const file of ["site.json", "data/export_screener.parquet"]) {
    expect((await request.get(file)).status(), file).toBe(200);
  }
});

test("the answer is in the page before any JavaScript runs", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("http://localhost:4173/Earnings-Watch/");
  await expect(page.getByTestId("flagged")).toHaveText("9");
  await expect(page.getByTestId("universe")).toHaveText("39");
  await expect(page.getByTestId("view-name")).toHaveText("after restatements");
  await context.close();
});

test("the view toggle changes the number, its universe and its name together", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "As first reported" }).click();
  await expect(page.getByTestId("flagged")).toHaveText("10");
  await expect(page.getByTestId("view-name")).toHaveText("as first reported");
  await expect(page.locator(".shown")).toHaveText("Showing 10 of 10");
});

test("the overview draws the pipeline in order, with the check that holds this site", async ({ page }) => {
  await open(page);
  const flow = page.getByRole("list").filter({ hasText: "Every check passes?" });
  await expect(flow.locator(":scope > li > b")).toHaveText([
    "SEC EDGAR", "S3", "Spark on EMR", "Snowflake", "dbt", "Every check passes?", "This site",
  ]);
  await expect(flow).toContainText("No: this site keeps its last good data.");
  // A day's test count adds up every dbt run of the day, so the overview shows none.
  await expect(flow).not.toContainText("tests passed");
  await page.getByRole("link", { name: "See the full pipeline" }).click();
  await expect(page).toHaveURL(/\/Earnings-Watch\/pipeline\/$/);
});

test("on a phone the pipeline reads top to bottom, within the screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const flow = page.getByRole("list").filter({ hasText: "Every check passes?" });
  await expect(flow).toHaveCSS("flex-direction", "column");
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits).toBe(true);
});

test("search and industry filters narrow the table", async ({ page }) => {
  await open(page);
  await page.getByLabel("Search a company").fill("Fixture Co 40");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.getByLabel("Search a company").fill("no such company");
  await expect(page.locator("tbody")).toContainText("No flagged company matches");
  await page.getByLabel("Search a company").fill("");
  await page.getByRole("button", { name: "Technology" }).click();
  await expect(page.locator("tbody tr td:nth-child(2)")).toHaveText(Array(2).fill("Technology"));
});

test.describe("keyboard shortcuts", () => {
  test("digits open pages in tab order", async ({ page }) => {
    await open(page);
    await page.keyboard.press("2");
    await expect(page).toHaveURL(/\/Earnings-Watch\/company\/$/);
    await page.keyboard.press("0");
    await expect(page).toHaveURL(/\/Earnings-Watch\/$/);
  });

  for (const modifier of ["Control", "Meta", "Alt"]) {
    test(`${modifier}+digit is left to the browser`, async ({ page }) => {
      await open(page);
      await page.keyboard.press(`${modifier}+3`);
      await page.waitForTimeout(300);
      await expect(page).toHaveURL(/\/Earnings-Watch\/$/);
    });
  }

  test("typing a digit in a box types it and changes no page", async ({ page }) => {
    await open(page);
    await page.getByLabel("Search a company").click();
    await page.keyboard.type("5");
    await expect(page.getByLabel("Search a company")).toHaveValue("5");
    await expect(page).toHaveURL(/\/Earnings-Watch\/$/);
  });

  test("/ searches, ? lists the shortcuts, digits wait while the list is open, Esc closes it", async ({ page }) => {
    await open(page);
    await page.keyboard.press("/");
    await expect(page.getByLabel("Search a company")).toBeFocused();
    await page.locator("body").click({ position: { x: 5, y: 300 } });
    await page.keyboard.press("?");
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
    await page.keyboard.press("4");
    await expect(page).toHaveURL(/\/Earnings-Watch\/$/);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
  });
});

test.describe("themes", () => {
  test("paper by default, even when the system prefers dark", async ({ browser }) => {
    const context = await browser.newContext({ colorScheme: "dark" });
    const page = await context.newPage();
    await page.goto("http://localhost:4173/Earnings-Watch/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await context.close();
  });

  test("the terminal theme, once chosen, is remembered", async ({ page }) => {
    await open(page);
    await page.getByRole("button", { name: "Terminal" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.getByRole("button", { name: "Paper" })).toBeVisible();
  });

  test("with storage blocked, the site still opens, in paper", async ({ browser }) => {
    const context = await browser.newContext();
    await context.addInitScript(() => {
      Object.defineProperty(window, "localStorage", { get: () => { throw new Error("blocked"); } });
    });
    const page = await context.newPage();
    const problems = watch(page);
    await open(page, "http://localhost:4173/Earnings-Watch/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.getByRole("button", { name: "Terminal" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    expect(problems).toEqual([]);
    await context.close();
  });
});

test("dates are shown in UTC, wherever the visitor is", async ({ browser }) => {
  const context = await browser.newContext({ timezoneId: "America/New_York" });
  const page = await context.newPage();
  await page.goto("http://localhost:4173/Earnings-Watch/");
  await expect(page.getByTestId("through")).toHaveText("Q3 2026");
  await expect(page.locator(".status [title]")).toHaveAttribute("title", "The newest quarter in the data ends 2026-09-30");
  await expect(page.locator(".status")).toContainText("06:05 UTC");
  await expect(page.locator("tbody tr").first().locator("td").last()).toHaveText("2026-09-30");
  await context.close();
});

test("with reduced motion, the query does not type itself", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  await page.goto("http://localhost:4173/Earnings-Watch/");
  const animation = await page.locator(".typed").evaluate((el) => getComputedStyle(el).animationName);
  expect(animation).toBe("none");
  await context.close();
});
