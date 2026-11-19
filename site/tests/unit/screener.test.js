// The screener's logic on its own: node --test, no browser (npm run test:unit).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEFAULT,
  filterRows,
  parseState,
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
  company_name: "Acme",
  industry_group: "Technology",
  filer_group: "accelerated",
  ttm_net_income: 120,
  prior_ttm_net_income: 100,
  ttm_operating_cash_flow: 50,
  prior_ttm_operating_cash_flow: 60,
  accruals_to_assets: 0.15,
  is_flagged: true,
  ...over,
});

test("a row: numbers from BigInt and decimals, the quarter in UTC, growth from a positive base", () => {
  const r = toRow(raw());
  assert.equal(r.cik, 1);
  assert.equal(r.quarter, "2026-09-30");
  assert.ok(Math.abs(/** @type {number} */ (r.growth) - 0.2) < 1e-9);
  assert.equal(toRow(raw({ prior_ttm_net_income: -5 })).growth, null);
  assert.equal(toRow(raw({ prior_ttm_net_income: 0 })).growth, null);
  assert.equal(toRow(raw({ company_name: null })).name, "CIK 1");
});

test("the address round-trips, and keeps only what differs from the default", () => {
  assert.equal(toSearch(DEFAULT), "");
  const s = { ...DEFAULT, view: "first_reported", q: " acme ", industry: "Technology", filer: "accelerated", flagged: true, sort: "name", dir: /** @type {const} */ ("asc"), growth: [0, 1.23456], gap: [0.1, 0.5] };
  const search = toSearch(s);
  assert.equal(search, "?view=first_reported&q=acme&industry=Technology&filer=accelerated&flagged=1&sort=name&dir=asc&growth=0%2C1.235&gap=0.1%2C0.5");
  assert.deepEqual(parseState(new URLSearchParams(search)), { ...s, q: "acme", growth: [0, 1.235] });
});

test("anything in the address not understood keeps its default", () => {
  const s = parseState(new URLSearchParams("view=x&filer=huge&sort=evil&dir=up&growth=1,0&gap=a,b&flagged=yes"));
  assert.deepEqual(s, DEFAULT);
  assert.deepEqual(parseState(new URLSearchParams("sort=name")).dir, "asc");
  assert.deepEqual(parseState(new URLSearchParams("growth=-9,9")).growth, [-1, 4]);
});

test("filters combine; an area keeps only charted companies, those beyond it at the edge", () => {
  const rows = [
    toRow(raw()),
    toRow(raw({ cik: 2n, company_name: "Beta", is_flagged: false, accruals_to_assets: 0.02 })),
    toRow(raw({ cik: 3n, company_name: "Gamma", prior_ttm_net_income: -1, industry_group: "Energy" })),
    toRow(raw({ cik: 4n, company_name: "Delta", ttm_net_income: 10000, accruals_to_assets: 0.9 })),
    toRow(raw({ cik: 1n, reporting_view: "first_reported" })),
  ];
  const names = (/** @type {any} */ s) => filterRows(rows, { ...DEFAULT, ...s }).map((r) => r.name);
  assert.deepEqual(names({}), ["Acme", "Beta", "Gamma", "Delta"]);
  assert.deepEqual(names({ flagged: true, industry: "Technology" }), ["Acme", "Delta"]);
  assert.deepEqual(names({ q: "ETA" }), ["Beta"]);
  assert.deepEqual(names({ q: "3" }), ["Gamma"]);
  assert.deepEqual(names({ gap: [0.1, 0.5] }), ["Acme", "Gamma", "Delta"]);
  assert.deepEqual(names({ growth: [0, 4] }), ["Acme", "Beta", "Delta"]);
  assert.deepEqual(names({ view: "first_reported" }), ["Acme"]);
});

test("sorting puts missing values last either way, then sorts by name", () => {
  const rows = [
    toRow(raw({ cik: 1n, company_name: "B", prior_ttm_net_income: -1 })),
    toRow(raw({ cik: 2n, company_name: "A", ttm_net_income: 300 })),
    toRow(raw({ cik: 3n, company_name: "C" })),
    toRow(raw({ cik: 4n, company_name: "D" })),
  ];
  const order = (/** @type {"asc" | "desc"} */ dir) => sortRows(rows, "growth", dir).map((r) => r.name);
  assert.deepEqual(order("desc"), ["A", "C", "D", "B"]);
  assert.deepEqual(order("asc"), ["C", "D", "A", "B"]);
  assert.deepEqual(sortRows(rows, "filer", "asc").map((r) => r.name), ["A", "B", "C", "D"]);
});

test("each view counts its universe and flags", () => {
  const rows = [toRow(raw()), toRow(raw({ cik: 2n, is_flagged: false })), toRow(raw({ reporting_view: "first_reported" }))];
  assert.deepEqual(summarize(rows), {
    latest: { universe: 2, flagged: 1 },
    first_reported: { universe: 1, flagged: 1 },
  });
});

test("the quarter most companies have reported through, not the newest period end", () => {
  assert.deepEqual(typicalQuarter(["2026-06-30", "2026-06-30", "2026-08-31"]), { label: "Q2 2026", newest: "2026-08-31" });
  assert.deepEqual(typicalQuarter(["2026-06-30", "2026-09-30", "2026-09-30"]).label, "Q3 2026");
  // Exactly half is not most.
  assert.deepEqual(typicalQuarter(["2026-06-30", "2026-09-30"]).label, "Q2 2026");
  assert.deepEqual(typicalQuarter(["2025-12-31", "2026-01-31", "2026-03-31"]).label, "Q1 2026");
  assert.deepEqual(typicalQuarter([]).label, "no data");
});
