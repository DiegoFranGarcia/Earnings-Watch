// The filing-timeliness page's logic on its own: node --test, no browser (npm run test:unit).
import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT, completeThrough, parseState, series, share, splitYear, toCells, toSearch, yearOf } from "#lib/timeliness.js";

/** @param {Record<string, any>} over */
const row = (over) => ({
  filer_group: "non_accelerated",
  form: "10-K",
  period_year: 2025n,
  filings: 4000n,
  on_time_filings: 3040n,
  within_extension_filings: 576n,
  late_filings: 384n,
  late_notices: 614n,
  notice_data_available: true,
  deadline_days: 90n,
  extension_days: 15n,
  median_days_to_file: 86,
  p90_days_to_file: 104,
  median_days_past_due_when_late: 12,
  ...over,
});

test("a row: numbers from BigInt, the on-time share, groups in order", () => {
  const cells = toCells([row({}), row({ filer_group: "large_accelerated", filings: 1500n, on_time_filings: 1470n })]);
  assert.deepEqual(cells.map((c) => c.group), ["large_accelerated", "non_accelerated"]);
  assert.equal(cells[1].filings, 4000);
  assert.equal(cells[1].deadline, 90);
  assert.equal(share(cells[1]), 0.76);
  assert.equal(share(cells[0]), 0.98);
  assert.equal(share({ onTime: 0, filings: 0 }), null);
});

test("an export from before the page (a row per filer status): counts summed, medians unknown", () => {
  const old = (/** @type {Record<string, any>} */ over) => {
    const { deadline_days, extension_days, ...r } = row(over);
    return r;
  };
  const [c] = toCells([
    old({ filer_status: "4-NON", filings: 3000n, on_time_filings: 2400n }),
    old({ filer_status: "5-SML", filings: 1000n, on_time_filings: 640n, notice_data_available: false }),
  ]);
  assert.equal(c.filings, 4000);
  assert.equal(c.onTime, 3040);
  assert.equal(c.noticeData, false);
  assert.equal(c.deadline, null);
  assert.equal(c.median, null);
});

test("a period year is complete once every filing, extensions included, was due: from May 1", () => {
  assert.equal(completeThrough("2026-11-19T06:05:21+00:00"), 2025);
  assert.equal(completeThrough("2026-05-01T00:00:00+00:00"), 2025);
  assert.equal(completeThrough("2026-04-30T23:00:00+00:00"), 2024);
});

test("lines from 2009, a group per line; the split's year has notices for every group", () => {
  const cells = toCells([
    row({ period_year: 2008n }),
    row({ period_year: 2024n, notice_data_available: false }),
    row({}),
    row({ period_year: 2026n }),
    row({ filer_group: "large_accelerated", period_year: 2025n, notice_data_available: false }),
    row({ form: "10-Q", period_year: 2026n }),
  ]);
  const lines = series(cells, "10-K");
  assert.deepEqual(lines.map((l) => l.group), ["large_accelerated", "accelerated", "non_accelerated"]);
  assert.deepEqual(lines[2].points.map((p) => p.year), [2024, 2025, 2026]);
  assert.deepEqual(yearOf(cells, "10-K", 2025).map((c) => c.group), ["large_accelerated", "non_accelerated"]);
  // 2025 lacks the large filers' notices; 2026 has them but is to date; nothing complete yet.
  assert.equal(splitYear(cells, "10-K", 2025), 2026);
  assert.equal(splitYear(toCells([row({})]), "10-K", 2025), 2025);
  assert.equal(splitYear(toCells([row({ notice_data_available: false })]), "10-K", 2025), null);
  assert.equal(splitYear(cells, "10-Q", 2025), 2026);
});

test("the address keeps the form, and only when it is not the default", () => {
  assert.equal(toSearch(DEFAULT), "");
  assert.equal(toSearch({ form: "10-Q" }), "?form=10-Q");
  assert.deepEqual(parseState(new URLSearchParams("form=10-Q")), { form: "10-Q" });
  assert.deepEqual(parseState(new URLSearchParams("form=8-K")), DEFAULT);
});
