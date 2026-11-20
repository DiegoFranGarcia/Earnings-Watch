// The restatements page's logic on its own: node --test, no browser (npm run test:unit).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEFAULT,
  awaitingFigures,
  barValue,
  filterRestatements,
  headline,
  parseState,
  sortRestatements,
  toRestatement,
  toSearch,
  yearly,
} from "#lib/restatements.js";

/** @param {number} year @param {string} kind @param {number} restated @param {number} companies */
const row = (year, kind, restated, companies, metric = "net_income", reporting = 4000) => ({
  change_year: year,
  restatement_kind: kind,
  metric,
  restatements: restated,
  companies_by_first_kind: companies,
  reporting_companies: reporting,
  median_days_to_first_change: kind === "correction" ? 98 : 365,
});

const summary = [
  row(2025, "correction", 60, 50),
  row(2025, "recast", 540, 400),
  row(2025, "tag_switch", 200, 150),
  row(2024, "correction", 30, 30, "net_income", 3000),
  row(2025, "correction", 9, 9, "revenue"),
];

test("the opening: the share of changed figures that came in an amendment, tag switches aside", () => {
  const h = headline(yearly(summary, "net_income"), 2025);
  assert.equal(h.share, 0.1);
  assert.equal(h.companies, 450);
  assert.equal(h.reporting, 4000);
  assert.equal(h.days, 98);
  assert.equal(headline(yearly(summary, "net_income"), 2030).share, null);
});

test("each year, for one figure: companies under their first kind, as a share or a count", () => {
  const years = yearly(summary, "net_income");
  assert.deepEqual(years.map((y) => y.year), [2024, 2025]);
  assert.equal(barValue(years[1], "recast", false), 0.1);
  assert.equal(barValue(years[1], "recast", true), 400);
  assert.equal(barValue(years[0], "recast", true), 0);
  assert.equal(barValue({ year: 2009, reporting: null, kinds: {} }, "recast", false), null);
  assert.equal(yearly(summary, "revenue").length, 1);
});

const raw = (/** @type {Record<string, any>} */ over) => ({
  restatement_key: "r1",
  cik: 1n,
  company_name: "Acme",
  metric: "net_income",
  restatement_kind: "correction",
  period_end: new Date("2024-12-31T00:00:00Z"),
  first_change_form: "10-K/A",
  first_change_at: new Date("2025-06-02T09:00:00Z"),
  days_to_first_change: 102n,
  first_reported_value: 100,
  latest_value: 80,
  restatement_amount: -20,
  change_to_assets: 0.02,
  selected_by: "amount",
  ...over,
});

test("the table: one figure, tag switches only when included, by kind and year, in the order chosen", () => {
  const rows = [
    toRestatement(raw({})),
    toRestatement(raw({ restatement_key: "r2", restatement_amount: 500, change_to_assets: 0.001, restatement_kind: "recast" })),
    toRestatement(raw({ restatement_key: "r3", restatement_amount: -5, change_to_assets: 0.4, first_change_at: new Date("2024-03-01T09:00:00Z") })),
    toRestatement(raw({ restatement_key: "r4", restatement_kind: "tag_switch" })),
    toRestatement(raw({ restatement_key: "r5", metric: "revenue" })),
  ];
  assert.equal(rows[0].cik, 1);
  assert.equal(rows[0].days, 102);
  assert.equal(rows[0].year, 2025);
  const keys = (/** @type {any} */ s, order = "amount") => sortRestatements(filterRestatements(rows, { ...DEFAULT, ...s }), order).map((r) => r.key);
  assert.deepEqual(keys({}), ["r2", "r1", "r3"]);
  assert.deepEqual(keys({ tags: true }), ["r2", "r1", "r4", "r3"]);
  assert.deepEqual(keys({ kind: "correction" }), ["r1", "r3"]);
  assert.deepEqual(keys({ year: 2024 }), ["r3"]);
  assert.deepEqual(keys({}, "share"), ["r3", "r1", "r2"]);
  assert.deepEqual(keys({}, "recent"), ["r1", "r2", "r3"]);
  assert.deepEqual(keys({ metric: "revenue" }), ["r5"]);
});

test("the address round-trips; a tag-switch kind needs tag switches included", () => {
  assert.equal(toSearch(DEFAULT), "");
  const s = { metric: "revenue", tags: true, counts: true, kind: "tag_switch", year: 2024, order: "share" };
  assert.equal(toSearch(s), "?metric=revenue&tags=1&counts=1&kind=tag_switch&year=2024&order=share");
  assert.deepEqual(parseState(new URLSearchParams(toSearch(s))), s);
  assert.equal(parseState(new URLSearchParams("kind=tag_switch")).kind, "");
  assert.deepEqual(parseState(new URLSearchParams("metric=x&year=abc&order=evil&kind=nope")), DEFAULT);
});

test("an export from before the chart's figures: the page waits for the next one", () => {
  assert.equal(awaitingFigures(summary), false);
  const old = summary.map(({ reporting_companies, companies_by_first_kind, ...r }) => r);
  assert.equal(awaitingFigures(old), true);
  assert.equal(awaitingFigures([]), false);
});
