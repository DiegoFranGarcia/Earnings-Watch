// The screener's logic on its own: node --test, no browser (npm run test:unit).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEFAULT,
  filterRows,
  parseState,
  prepare,
  sortRows,
  summarize,
  toRow,
  toSearch,
  typicalQuarter,
} from "#lib/screener.js";

/** @param {Record<string, any>} over */
const raw = (over = {}) => ({
  cik: 1n,
  reporting_view: "latest",
  period_end: new Date("2026-09-30T00:00:00Z"),
  known_at: new Date("2026-11-02T21:15:00Z"),
  company_name: "Acme",
  industry_group: "Technology",
  filer_group: "accelerated",
  ttm_net_income: 120,
  prior_ttm_net_income: 100,
  ttm_operating_cash_flow: 50,
  prior_ttm_operating_cash_flow: 60,
  average_total_assets: 400,
  accruals: 70,
  accruals_to_assets: 0.175,
  is_flagged: true,
  is_implausible: false,
  ...over,
});

test("a row: numbers from BigInt and decimals, dates in UTC, change over assets, growth from a positive base", () => {
  const r = toRow(raw());
  assert.equal(r.cik, 1);
  assert.equal(r.quarter, "2026-09-30");
  assert.equal(r.filed, "2026-11-02");
  assert.equal(r.change, 0.05);
  assert.ok(Math.abs(/** @type {number} */ (r.growth) - 0.2) < 1e-9);
  // From a loss: no growth figure, but the change is still drawn.
  const loss = toRow(raw({ prior_ttm_net_income: -80 }));
  assert.equal(loss.growth, null);
  assert.equal(loss.change, 0.5);
  assert.equal(toRow(raw({ average_total_assets: null })).change, null);
  assert.equal(toRow(raw({ company_name: null })).name, "CIK 1");
});

test("the chart agrees with the flag: income rising is the same test as a positive change", () => {
  for (const [ni, prior] of [[120, 100], [-10, -50], [5, 0], [100, 120], [-50, -10]]) {
    const r = toRow(raw({ ttm_net_income: ni, prior_ttm_net_income: prior }));
    assert.equal(/** @type {number} */ (r.change) > 0, ni > prior, `${ni} from ${prior}`);
  }
});

test("the address round-trips, and keeps only what differs from the default", () => {
  assert.equal(toSearch(DEFAULT), "");
  const s = { ...DEFAULT, view: "first_reported", q: " acme ", industry: "Technology", filer: "accelerated", flagged: true, behind: true, sort: "name", dir: /** @type {const} */ ("asc"), change: [0, 0.23456], gap: [0.1, 0.5] };
  const search = toSearch(s);
  assert.equal(search, "?view=first_reported&q=acme&industry=Technology&filer=accelerated&flagged=1&behind=1&sort=name&dir=asc&change=0%2C0.235&gap=0.1%2C0.5");
  assert.deepEqual(parseState(new URLSearchParams(search)), { ...s, q: "acme", change: [0, 0.235] });
});

test("anything in the address not understood keeps its default", () => {
  const s = parseState(new URLSearchParams("view=x&filer=huge&sort=evil&dir=up&change=1,0&gap=a,b&flagged=yes&behind=true"));
  assert.deepEqual(s, DEFAULT);
  assert.deepEqual(parseState(new URLSearchParams("sort=name")).dir, "asc");
  assert.deepEqual(parseState(new URLSearchParams("change=-9,9")).change, [-1, 1]);
});

test("the quarter most companies have reported through, not the newest period end", () => {
  assert.deepEqual(typicalQuarter(["2026-06-30", "2026-06-30", "2026-08-31"]), { index: 2026 * 4 + 1, label: "Q2 2026", newest: "2026-08-31" });
  assert.equal(typicalQuarter(["2026-06-30", "2026-09-30", "2026-09-30"]).label, "Q3 2026");
  // Exactly half is not most.
  assert.equal(typicalQuarter(["2026-06-30", "2026-09-30"]).label, "Q2 2026");
  assert.equal(typicalQuarter(["2025-12-31", "2026-01-31", "2026-03-31"]).label, "Q1 2026");
  assert.equal(typicalQuarter([]).label, "no data");
});

test("behind on filings: a latest quarter more than two quarters before most companies'", () => {
  const { rows, through } = prepare([
    toRow(raw({ cik: 1n })),
    toRow(raw({ cik: 2n })),
    toRow(raw({ cik: 3n })),
    toRow(raw({ cik: 4n, period_end: new Date("2026-03-31T00:00:00Z") })), // Q1: two behind
    toRow(raw({ cik: 5n, period_end: new Date("2025-12-31T00:00:00Z") })), // Q4 2025: three
  ]);
  assert.equal(through.label, "Q3 2026");
  assert.deepEqual(rows.map((r) => r.behind), [false, false, false, false, true]);
  assert.deepEqual(summarize(rows).latest, { universe: 4, flagged: 4, behind: 1 });
  assert.equal(filterRows(rows, DEFAULT).length, 4);
  assert.equal(filterRows(rows, { ...DEFAULT, behind: true }).length, 5);
});

test("filters combine; an area keeps companies where they are drawn, beyond it at the edge", () => {
  const rows = [
    toRow(raw()),
    toRow(raw({ cik: 2n, company_name: "Beta", is_flagged: false, accruals_to_assets: 0.02 })),
    toRow(raw({ cik: 3n, company_name: "Gamma", prior_ttm_net_income: -100, industry_group: "Energy" })),
    toRow(raw({ cik: 4n, company_name: "Delta", ttm_net_income: 10000, accruals_to_assets: 8.2 })),
    toRow(raw({ cik: 1n, reporting_view: "first_reported" })),
  ];
  const names = (/** @type {any} */ s) => filterRows(rows, { ...DEFAULT, ...s }).map((r) => r.name);
  assert.deepEqual(names({}), ["Acme", "Beta", "Gamma", "Delta"]);
  assert.deepEqual(names({ flagged: true, industry: "Technology" }), ["Acme", "Delta"]);
  assert.deepEqual(names({ q: "ETA" }), ["Beta"]);
  assert.deepEqual(names({ q: "3" }), ["Gamma"]);
  // Delta's gap of 820% is drawn, and selected, at the top edge (100%).
  assert.deepEqual(names({ gap: [0.9, 1] }), ["Delta"]);
  assert.deepEqual(names({ change: [0.4, 1] }), ["Gamma", "Delta"]);
  assert.deepEqual(names({ view: "first_reported" }), ["Acme"]);
});

test("the default order: flagged first, then the largest gap in dollars, not as a share of assets", () => {
  const rows = [
    toRow(raw({ cik: 1n, company_name: "Tiny", accruals: 900, accruals_to_assets: 8.2 })),
    toRow(raw({ cik: 2n, company_name: "Huge", accruals: 9000, accruals_to_assets: 0.41 })),
    toRow(raw({ cik: 3n, company_name: "Unflagged", is_flagged: false, accruals: 99999, accruals_to_assets: 0.2 })),
    toRow(raw({ cik: 4n, company_name: "Nothing", accruals: null })),
  ];
  const order = (/** @type {string} */ key, /** @type {"asc" | "desc"} */ dir) => sortRows(rows, key, dir).map((r) => r.name);
  assert.deepEqual(order(DEFAULT.sort, DEFAULT.dir), ["Huge", "Tiny", "Nothing", "Unflagged"]);
  assert.deepEqual(order("gap", "desc"), ["Tiny", "Huge", "Unflagged", "Nothing"]);
  assert.deepEqual(order("accruals", "asc"), ["Tiny", "Huge", "Unflagged", "Nothing"]);
});
