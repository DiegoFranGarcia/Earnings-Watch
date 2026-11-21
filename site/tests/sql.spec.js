// The SQL page in real browsers (Chromium, Firefox and WebKit: see playwright.config.js), against
// the fixture export, with DuckDB, its worker, its Parquet extension and the data all served by
// tests/serve.mjs as GitHub Pages serves them, gzip and all. Every example query runs here, so a
// renamed column breaks the build instead of the demo.
import { expect, test } from "@playwright/test";
import { EXAMPLES } from "../src/lib/sql.js";

/**
 * Every request the page makes, so a test can say none left the site, or none fetched DuckDB.
 * @param {import("@playwright/test").Page} page
 */
function watch(page) {
  /** @type {{ url: string, status: number, range: string | undefined }[]} */
  const seen = [];
  page.on("response", (r) => seen.push({ url: r.url(), status: r.status(), range: r.request().headers().range }));
  return seen;
}

/** @param {import("@playwright/test").Page} page */
async function open(page, hash = "") {
  await page.goto(`sql/${hash}`);
  await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
}

/**
 * Type a query and run it; wait for its result or its error.
 * @param {import("@playwright/test").Page} page
 * @param {string} sql
 */
async function run(page, sql) {
  await page.getByTestId("editor").fill(sql);
  await page.getByTestId("run").click();
  await expect(page.getByTestId("status").or(page.getByTestId("error"))).toBeVisible({ timeout: 60_000 });
}

test("before a click: the tables and examples are in the page, and DuckDB is not downloaded", async ({ page }) => {
  const seen = watch(page);
  await open(page);
  await expect(page.locator("details[data-table]")).toHaveCount(7);
  await expect(page.locator('details[data-table="export_screener"] summary')).toContainText("rows");
  await expect(page.locator("[data-example]")).toHaveCount(EXAMPLES.length);
  await expect(page.getByTestId("run")).toContainText(/Start DuckDB and run downloads about \d+ MB/);
  await page.waitForTimeout(500);
  expect(seen.filter((r) => /\.wasm|worker|\.parquet/.test(r.url))).toEqual([]);
});

test("a shared link fills the editor and waits for a click", async ({ page }) => {
  const seen = watch(page);
  const sql = "select count(*) as companies from export_screener where reporting_view = 'latest'";
  await open(page, `#sql=${encodeURIComponent(sql)}`);
  await expect(page.getByTestId("editor")).toHaveValue(sql);
  await expect(page.getByTestId("note")).toContainText("came from a link");
  await page.waitForTimeout(500);
  expect(seen.filter((r) => /\.wasm|worker|\.parquet/.test(r.url))).toEqual([]);
});

test("every example runs against the export, from this site only, each table downloaded whole", async ({ page }) => {
  test.setTimeout(180_000);
  /** @type {string[]} */
  const problems = [];
  page.on("pageerror", (e) => problems.push(e.message));
  const seen = watch(page);
  await open(page);
  for (const example of EXAMPLES) {
    await page.locator(`[data-example="${example.id}"]`).click();
    await expect(page.getByTestId("editor")).toHaveValue(example.sql);
    await page.getByTestId("run").click();
    await expect(page.getByTestId("status").or(page.getByTestId("error"))).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("error"), `${example.id} failed`).toHaveCount(0);
    await expect(page.getByTestId("status")).toContainText(/\d+ rows? in \d+ ms/);
    await expect(page.getByTestId("run")).toContainText("Run");
  }
  // The query is in the address to share, after the fragment only.
  expect(new URL(page.url()).hash).toMatch(/^#sql=/);
  expect(new URL(page.url()).search).toBe("");
  expect(seen.filter((r) => !r.url.startsWith("http://localhost:4173/"))).toEqual([]);
  expect(seen.some((r) => r.url.endsWith("/duckdb/v1.4.3/wasm_eh/parquet.duckdb_extension.wasm") && r.status === 200)).toBe(true);
  // Whole files, never byte ranges (ADR 20): each table in one request, at the address of the
  // export it belongs to, so no earlier export's cached copy can answer any part of it.
  expect(seen.filter((r) => r.range !== undefined)).toEqual([]);
  const tables = seen.filter((r) => new URL(r.url).pathname.endsWith(".parquet"));
  expect(tables.map((r) => new URL(r.url).pathname.split("/").pop()).sort()).toEqual(
    (await page.locator("details[data-table]").evaluateAll((els) => els.map((e) => e.getAttribute("data-table")))).map((t) => `${t}.parquet`).sort(),
  );
  for (const r of tables) {
    expect(r.status, r.url).toBe(200);
    expect(new URL(r.url).searchParams.get("v"), r.url).toBe("fixture");
  }
  expect(problems).toEqual([]);
});

test("results are capped on screen and in the CSV, with the full count reported", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page);
  await run(page, "select range as n from range(5000)");
  await expect(page.getByTestId("status")).toHaveText(/^5,000 rows in [\d,]+ ms: showing the first 1,000\.$/);
  await expect(page.getByTestId("result").locator("tbody tr")).toHaveCount(1000);

  await run(page, "select range as n, '=1+1' as formula from range(150000)");
  await expect(page.getByTestId("status")).toContainText("the CSV holds the first 100,000");
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("csv").click()]);
  const csv = await (await download.createReadStream()).toArray();
  const lines = Buffer.concat(csv).toString("utf8").trimEnd().split("\r\n");
  expect(lines.length).toBe(100_001);
  expect(lines[1]).toBe("0,'=1+1");
});

test("mistakes read plainly: a wrong column, and an extension the console does not have", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page);
  await run(page, "select no_such_column from export_screener");
  await expect(page.getByTestId("error")).toHaveAttribute("data-kind", "sql");
  await expect(page.getByTestId("error")).toContainText("no_such_column");
  await run(page, `select '{"a": 1}'::json ->> 'a' as a`);
  await expect(page.getByTestId("error")).toHaveAttribute("data-kind", "extension");
  // The console still works after both.
  await run(page, "select 42 as answer");
  await expect(page.getByTestId("result")).toContainText("42");
});

test("a table that does not match site.json is never queried: the page asks for a reload", async ({ page }) => {
  test.setTimeout(120_000);
  // site.json as a visitor's browser might get it right after a deploy: one table's hash is not
  // the hash of the file it downloads.
  await page.route("**/Earnings-Watch/site.json", async (route) => {
    const live = await (await route.fetch()).json();
    live.files["export_restatements_largest.parquet"].sha256 = "0".repeat(64);
    await route.fulfill({ json: live });
  });
  await open(page);
  await run(page, "select count(*) from export_restatements_largest");
  await expect(page.getByTestId("error")).toHaveAttribute("data-kind", "stale");
  await expect(page.getByTestId("error")).toContainText("Reload the page");
  await expect(page.getByTestId("error")).toContainText("export_restatements_largest.parquet");
  await expect(page.getByTestId("result")).toHaveCount(0);
});

test("a table that cannot be downloaded says so, and the next run tries again", async ({ page }) => {
  test.setTimeout(120_000);
  let refuse = true;
  await page.route("**/data/export_pipeline_health.parquet*", (route) => (refuse ? route.fulfill({ status: 503 }) : route.fallback()));
  await open(page);
  await run(page, "select 1 as one");
  await expect(page.getByTestId("error")).toHaveAttribute("data-kind", "download");
  await expect(page.getByTestId("error")).toContainText("could not be downloaded");
  refuse = false;
  await run(page, "select count(*) as days from export_pipeline_health");
  await expect(page.getByTestId("result")).toContainText("30");
});

test("Stop ends a runaway query at once, and the next run starts DuckDB again", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page);
  await run(page, "select 1 as warm");
  await page.getByTestId("editor").fill("select sum(a.range * b.range) from range(100000000) a, range(100000000) b");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("stop")).toBeVisible();
  await page.getByTestId("stop").click();
  await expect(page.getByTestId("note")).toContainText("Stopped");
  await expect(page.getByTestId("run")).toContainText("Start DuckDB and run");
  await run(page, "select 'again' as state");
  await expect(page.getByTestId("result")).toContainText("again");
});

test("only the SQL page allows WebAssembly and workers; every other policy is the site's", async ({ request }) => {
  const policy = async (/** @type {string} */ path) => {
    const html = await (await request.get(path)).text();
    const match = /<meta http-equiv="content-security-policy" content="([^"]*)"/.exec(html);
    expect(match, path).not.toBeNull();
    // Each page hashes its own inline scripts; the rest of the policy is the comparison.
    return /** @type {RegExpExecArray} */ (match)[1].replace(/ 'sha256-[^']+'/g, "");
  };
  const site = await policy("");
  for (const path of ["screener/", "company/", "restatements/", "timeliness/", "pipeline/"]) {
    expect(await policy(path), path).toBe(site);
  }
  expect(site).not.toContain("wasm-unsafe-eval");
  expect(site).not.toContain("worker-src");
  expect(await policy("sql/")).toBe(
    site.replace("script-src 'self'", "script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'"),
  );
});

test("on a phone: the editor, its buttons, the tables and a wide result fit, with no sideways scroll", async ({ browser }) => {
  test.setTimeout(120_000);
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await page.goto("http://localhost:4173/Earnings-Watch/sql/");
  await expect(page.locator("html")).toHaveAttribute("data-ready", "true");
  const width = () => page.evaluate(() => document.documentElement.scrollWidth);
  expect(await width()).toBeLessThanOrEqual(390);
  // A wide result scrolls inside its own box, not the page.
  await run(page, "select * from export_screener limit 50");
  await expect(page.getByTestId("result")).toBeVisible();
  expect(await width()).toBeLessThanOrEqual(390);
  await expect(page.getByTestId("editor")).toHaveAttribute("spellcheck", "false");
  await expect(page.getByTestId("editor")).toHaveAttribute("autocapitalize", "off");
  await expect(page.getByTestId("editor")).toHaveAttribute("autocorrect", "off");
  await context.close();
});
