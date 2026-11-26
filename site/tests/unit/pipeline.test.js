// The Pipeline page's logic on its own: node --test, no browser (npm run test:unit).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  EVENTS, FAULT_DRILLS, RETIRED_ON, STATES, longDate, months, statusLine, summarize, tense, times, toDays,
} from "#lib/pipeline.js";

/** @param {string} day @param {string} state @param {Record<string, any>} [over] */
const row = (day, state, over = {}) => ({
  date_day: new Date(`${day}T00:00:00Z`),
  day_state: state,
  run_expected: state !== "no_run_expected",
  first_exported_at: state === "met" ? new Date(`${day}T06:08:07Z`) : null,
  dollars: state === "no_run_expected" ? 0 : 0.04,
  ...over,
});

test("rows become days, oldest first, with the export's time in UTC", () => {
  const days = toDays([row("2026-11-20", "failed"), row("2026-11-19", "met")]);
  assert.deepEqual(days.map((d) => d.day), ["2026-11-19", "2026-11-20"]);
  assert.equal(days[0].exportedAt, "06:08");
  assert.equal(days[1].exportedAt, null);
  assert.equal(days[0].expected, true);
});

test("the record begins on its first day with a known outcome", () => {
  // As in an export from the old 30-day window: unrecorded days and a Sunday before the first run.
  const days = toDays([
    row("2026-10-31", "not_recorded"),
    row("2026-11-01", "no_run_expected"),
    row("2026-11-18", "not_recorded"),
    row("2026-11-19", "met"),
    row("2026-11-22", "no_run_expected"),
    row("2026-11-25", "not_recorded"), // the newest day, not yet complete: kept
  ]);
  assert.deepEqual(days.map((d) => d.day), ["2026-11-19", "2026-11-22", "2026-11-25"]);
  assert.deepEqual(toDays([row("2026-11-01", "no_run_expected"), row("2026-11-02", "not_recorded")]), []);
});

test("an unknown state is refused, not shown as something else", () => {
  assert.throws(() => toDays([row("2026-11-19", "sideways")]), /unknown day_state/);
});

test("on time counts only mornings a run was due and its outcome is known", () => {
  const days = toDays([
    row("2026-11-19", "met"),
    row("2026-11-20", "failed"),
    row("2026-11-21", "held"),
    row("2026-11-22", "no_run_expected"),
    row("2026-11-23", "no_run_expected"),
    row("2026-11-24", "met"),
    row("2026-11-25", "late"),
    row("2026-11-26", "not_recorded"),
  ]);
  const s = summarize(days);
  assert.equal(s.first, "2026-11-19");
  assert.equal(s.last, "2026-11-26");
  assert.equal(s.days, 8);
  assert.equal(s.due, 5); // met, failed, held, met, late: not the two weekends, not the unrecorded day
  assert.equal(s.onTime, 2);
  assert.equal(s.onTimeShare, 0.4);
  assert.equal(s.held, 1);
});

test("cost: the average per morning a run was due, and per 30-day month", () => {
  const days = toDays([
    row("2026-11-19", "met", { dollars: 0.05 }),
    row("2026-11-20", "met", { dollars: 0.15 }), // a quarterly load
    row("2026-11-21", "no_run_expected", { dollars: 0 }),
  ]);
  const s = summarize(days);
  assert.equal(Math.round(s.dollars * 100) / 100, 0.2);
  assert.equal(Math.round(/** @type {number} */ (s.perRun) * 1000) / 1000, 0.1);
  assert.equal(Math.round(/** @type {number} */ (s.perMonth) * 100) / 100, 2);
});

test("an empty record has no numbers rather than zeros", () => {
  const s = summarize([]);
  assert.equal(s.first, null);
  assert.equal(s.onTimeShare, null);
  assert.equal(s.perRun, null);
  assert.equal(s.perMonth, null);
});

test("the status line, running and after shutdown, with absolute dates only", () => {
  assert.equal(
    statusLine("2026-11-19", null),
    "Runs every business-day morning. Complete record since November 19, 2026.",
  );
  assert.equal(
    statusLine("2026-11-19", "2027-02-26"),
    "Ran every business-day morning until February 26, 2027. Complete record from November 19, 2026.",
  );
  assert.equal(tense("costs", "cost", null), "costs");
  assert.equal(tense("costs", "cost", "2027-02-26"), "cost");
  assert.equal(longDate("2026-01-05"), "January 5, 2026");
});

test("the setting ships switched on: the pipeline is running", () => {
  assert.equal(RETIRED_ON, null);
});

test("once, twice, n times", () => {
  assert.deepEqual([1, 2, 3].map(times), ["once", "twice", "3 times"]);
});

test("the calendar: each month keeps its shape, Monday first, days outside the record blank", () => {
  const days = toDays([row("2026-11-30", "met"), row("2026-12-01", "late"), row("2026-12-02", "met")]);
  const m = months(days);
  assert.deepEqual(m.map((x) => x.label), ["November 2026", "December 2026"]);
  const nov = m[0];
  assert.equal(nov.cells.length, 30);
  // November 1, 2026 is a Sunday: the last row of the first week.
  assert.deepEqual([nov.cells[0].row, nov.cells[0].col], [6, 0]);
  assert.equal(nov.weeks, 6);
  assert.equal(nov.cells[0].day, null); // before the record
  assert.equal(nov.cells[29].day?.state, "met");
  // December 1, 2026 is a Tuesday.
  assert.deepEqual([m[1].cells[0].row, m[1].cells[0].col], [1, 0]);
  assert.equal(m[1].cells[0].day?.state, "late");
  assert.equal(m[1].cells[2].day, null); // December 3: after the record
  assert.deepEqual(months([]), []);
});

test("every state the model can produce has a label and a meaning", () => {
  assert.deepEqual(
    STATES.map((s) => s.key).sort(),
    ["failed", "held", "late", "met", "missed", "no_run_expected", "not_recorded"],
  );
  for (const s of STATES) assert.ok(s.label && s.meaning.endsWith("."));
});

test("events: dated, oldest first, each linked to its write-up; three fault drills", () => {
  const dates = EVENTS.map((e) => e.date);
  assert.deepEqual(dates, [...dates].sort());
  for (const e of EVENTS) assert.match(e.href, /^https:\/\/github\.com\/DiegoFranGarcia\/Earnings-Watch\/blob\/main\/docs\//);
  assert.equal(FAULT_DRILLS, 3);
});
