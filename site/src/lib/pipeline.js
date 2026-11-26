// The Pipeline page's logic on its own (tests/unit/pipeline.test.js): the pipeline's whole record,
// day by day, from export_pipeline_health (one row per UTC day from the day its record began to the
// day before the export). Everything is phrased with absolute dates, so the page still reads
// correctly after the pipeline stops: then RETIRED_ON is set, and the page switches to the past
// tense. Nothing else changes.

/**
 * The one setting for shutting the pipeline down: null while it runs; the date of its last
 * morning ("YYYY-MM-DD") once it has stopped. The page's status line and tense follow it.
 * @type {string | null}
 */
export const RETIRED_ON = null;

const REPO = "https://github.com/DiegoFranGarcia/Earnings-Watch/blob/main/";

/**
 * Every state a day can be in, in the order the legend shows them, each with what it means.
 * The model decides the state (mart_pipeline_health.day_state); the page only shows it.
 */
export const STATES = [
  { key: "met", label: "On time", meaning: "Exported by 09:00 UTC, and every check passed." },
  { key: "late", label: "Late", meaning: "Exported after 09:00 UTC, and every check passed." },
  {
    key: "held",
    label: "Held back",
    meaning:
      "A volume check, test or model failed, so the build stopped and the site kept its last good data.",
  },
  {
    key: "failed",
    label: "Failed",
    meaning: "A task that lands, loads, builds or exports the data failed for another reason.",
  },
  { key: "missed", label: "Missed", meaning: "A run was due, nothing failed, and nothing was exported." },
  {
    key: "no_run_expected",
    label: "No run due",
    meaning: "The morning after a weekend or an SEC holiday: EDGAR published no new daily index.",
  },
  {
    key: "not_recorded",
    label: "Not recorded",
    meaning: "The run's task history was not complete when this export was made.",
  },
];

/** The states that count as a morning a run was due and its outcome is known. */
const DUE = new Set(["met", "late", "held", "failed", "missed"]);

/** What the cost figures include, and what they leave out. */
export const COST_COVERS =
  "Snowflake query compute and the Spark jobs on EMR Serverless, for the pipeline's own runs. " +
  "Not included: the time Snowflake's warehouses stay running between queries (idle time), " +
  "and AWS hosting (the EC2 host and S3 storage).";

/**
 * When things went wrong, or were made to go wrong on purpose: incidents, fault drills (a fault
 * injected into the real system) and the recovery drill. From docs/, not from the export.
 */
export const EVENTS = [
  {
    date: "2026-11-05",
    kind: "incident",
    text: "A day of SEC filings was never loaded: the run failed before alerts existed. Found and repaired on November 21; every morning now checks the last four weeks.",
    href: `${REPO}docs/incidents/2026-11-05.md`,
  },
  {
    date: "2026-11-09",
    kind: "drill",
    text: "Fault drill: 60% of a quarter's numbers deleted. The volume check stopped the build, and the finished tables stayed byte-for-byte the same.",
    href: `${REPO}docs/chaos.md#half-a-quarter-2026-11-09`,
  },
  {
    date: "2026-11-09",
    kind: "drill",
    text: "Fault drill: a quarter's columns reordered, as if the SEC had changed its files. The Spark job's header check rejected it; nothing was written.",
    href: `${REPO}docs/chaos.md#columns-reordered-2026-11-09`,
  },
  {
    date: "2026-11-13",
    kind: "recovery",
    text: "Recovery drill: the Airflow host destroyed and rebuilt from scratch, its history restored from the nightly backup, in 19 minutes 42 seconds.",
    href: `${REPO}docs/runbook.md#rebuild-the-host-from-scratch`,
  },
  {
    date: "2026-11-21",
    kind: "incident",
    text: "The morning build stopped on two tests that ran too early. Nothing wrong was published; the site kept the previous day's data until the fix.",
    href: `${REPO}docs/incidents/2026-11-21.md`,
  },
  {
    date: "2026-11-21",
    kind: "drill",
    text: "Fault drill: most of a day's filings deleted. The daily volume check stopped the build, and the live site kept its data.",
    href: `${REPO}docs/chaos.md#a-day-with-too-few-filings-2026-11-21`,
  },
];

/** Checks that are covered, but not by a drill on the running system: one undated line. */
export const ALSO_COVERED = {
  text: "Also covered: truncated downloads (a drill script and unit tests) and loading the same file twice (24.8 million rows reloaded, fingerprints unchanged).",
  href: `${REPO}docs/chaos.md`,
};

/** How many fault drills are listed: each was caught before bad data was published. */
export const FAULT_DRILLS = EVENTS.filter((e) => e.kind === "drill").length;

/** YYYY-MM-DD in UTC, from a Date or a string. @param {Date | string} value */
export const isoDay = (value) =>
  value instanceof Date ? value.toISOString().slice(0, 10) : String(value).slice(0, 10);

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** "2026-11-19" -> "November 19, 2026". @param {string} iso */
export function longDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/**
 * @typedef {{ day: string, state: string, exportedAt: string | null, dollars: number,
 *   expected: boolean }} Day
 */

/**
 * The export's rows as days, oldest first, from the first day with a known outcome: days before
 * the pipeline's first recorded run (not recorded, or no run due before any run) are not part of
 * its record. The model starts the record there already; an export made before it did (a 30-day
 * window) starts there too. Unknown states are refused rather than shown wrongly.
 * @param {Record<string, any>[]} rows
 * @returns {Day[]}
 */
export function toDays(rows) {
  const known = new Set(STATES.map((s) => s.key));
  const days = rows
    .map((r) => {
      if (!known.has(r.day_state)) throw new Error(`unknown day_state ${JSON.stringify(r.day_state)}`);
      return {
        day: isoDay(r.date_day),
        state: String(r.day_state),
        exportedAt: r.first_exported_at == null ? null : new Date(r.first_exported_at).toISOString().slice(11, 16),
        dollars: Number(r.dollars ?? 0),
        expected: Boolean(r.run_expected),
      };
    })
    .sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0));
  const start = days.findIndex((d) => DUE.has(d.state));
  return start === -1 ? [] : days.slice(start);
}

/**
 * The whole record in a few numbers.
 * @param {Day[]} days
 */
export function summarize(days) {
  /** @type {Record<string, number>} */
  const by = Object.fromEntries(STATES.map((s) => [s.key, 0]));
  for (const d of days) by[d.state] += 1;
  const due = days.filter((d) => DUE.has(d.state)).length;
  const runs = days.filter((d) => d.expected).length;
  const dollars = days.reduce((sum, d) => sum + d.dollars, 0);
  return {
    first: days.length ? days[0].day : null,
    last: days.length ? days[days.length - 1].day : null,
    days: days.length,
    by,
    /** Mornings a run was due and its outcome is known; on time = met. */
    due,
    onTime: by.met,
    onTimeShare: due ? by.met / due : null,
    /** Mornings the pipeline stopped itself rather than publish. */
    held: by.held,
    dollars,
    /** Average cost per morning a run was due (quarterly loads raise it when they land). */
    perRun: runs ? dollars / runs : null,
    /** The average day's cost, over a 30-day month. */
    perMonth: days.length ? (dollars / days.length) * 30 : null,
  };
}

/**
 * The status line, in the present tense while the pipeline runs and the past once it has stopped.
 * @param {string} first the first day of the record
 * @param {string | null} retiredOn
 */
export function statusLine(first, retiredOn = RETIRED_ON) {
  return retiredOn
    ? `Ran every business-day morning until ${longDate(retiredOn)}. Complete record from ${longDate(first)}.`
    : `Runs every business-day morning. Complete record since ${longDate(first)}.`;
}

/**
 * The present or the past form of a verb, as the pipeline runs or has stopped.
 * @param {string} present @param {string} past @param {string | null} retiredOn
 */
export const tense = (present, past, retiredOn = RETIRED_ON) => (retiredOn ? past : present);

/** "1 time", "2 times". @param {number} n */
export const times = (n) => (n === 1 ? "once" : n === 2 ? "twice" : `${n} times`);

/**
 * The calendar: one block per month, one column per week (Monday first), one cell per day. Days
 * of the month outside the record are blanks, so every month keeps its shape.
 * @param {Day[]} days
 */
export function months(days) {
  if (!days.length) return [];
  const byDay = new Map(days.map((d) => [d.day, d]));
  const first = new Date(`${days[0].day}T00:00:00Z`);
  const last = new Date(`${days[days.length - 1].day}T00:00:00Z`);
  const out = [];
  for (
    let m = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1));
    m <= last;
    m = new Date(Date.UTC(m.getUTCFullYear(), m.getUTCMonth() + 1, 1))
  ) {
    const year = m.getUTCFullYear();
    const month = m.getUTCMonth();
    const length = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    const offset = (m.getUTCDay() + 6) % 7; // Monday = 0
    const cells = [];
    for (let d = 1; d <= length; d += 1) {
      const iso = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const slot = offset + d - 1;
      cells.push({ iso, row: slot % 7, col: Math.floor(slot / 7), day: byDay.get(iso) ?? null });
    }
    out.push({
      key: `${year}-${String(month + 1).padStart(2, "0")}`,
      label: `${MONTHS[month]} ${year}`,
      weeks: Math.floor((offset + length - 1) / 7) + 1,
      cells,
    });
  }
  return out;
}

/** The label of a state. @param {string} key */
export const stateLabel = (key) => STATES.find((s) => s.key === key)?.label ?? key;
