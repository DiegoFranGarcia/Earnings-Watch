// The filing-timeliness page: original 10-Ks and 10-Qs by filer group, form and period year,
// on time, within a late-filing notice's extension, or late. Plain functions, used when the
// site is built and in the browser, tested on their own.

/** @type {[string, string][]} */
export const GROUPS = [
  ["large_accelerated", "Large accelerated"],
  ["accelerated", "Accelerated"],
  ["non_accelerated", "Non-accelerated"],
];
export const GROUP_LABELS = Object.fromEntries(GROUPS);
export const FORMS = ["10-K", "10-Q"];
/** The years XBRL tagging phased in: the largest companies from 2009, all others by 2011. */
export const PHASE_IN = [2009, 2011];
/** The first period year shown: earlier ones hold only filings made years late. */
export const FIRST_YEAR = 2009;

/**
 * One filer group's filings of one form for one period year.
 * @typedef {{
 *   group: string, form: string, year: number, filings: number, onTime: number,
 *   within: number, late: number, notices: number, noticeData: boolean,
 *   deadline: number | null, extension: number | null,
 *   median: number | null, p90: number | null, lateBy: number | null,
 * }} Cell
 */

/** @param {unknown} v */
const num = (v) => (v == null ? null : Number(v));

/**
 * The export's rows, one per group, form and year. An export from before the page (one row per
 * filer status, no deadlines) is summed by group: its counts add up, its medians do not, so
 * those are left unknown.
 * @param {Record<string, any>[]} rows export_filing_timeliness
 * @returns {Cell[]}
 */
export function toCells(rows) {
  /** @type {Map<string, Cell & { parts: number }>} */
  const cells = new Map();
  for (const r of rows) {
    if (!GROUP_LABELS[r.filer_group] || !FORMS.includes(r.form)) continue;
    const year = Number(r.period_year);
    const key = `${r.filer_group}|${r.form}|${year}`;
    const c = cells.get(key);
    if (!c) {
      cells.set(key, {
        group: r.filer_group,
        form: r.form,
        year,
        filings: Number(r.filings ?? 0),
        onTime: Number(r.on_time_filings ?? 0),
        within: Number(r.within_extension_filings ?? 0),
        late: Number(r.late_filings ?? 0),
        notices: Number(r.late_notices ?? 0),
        noticeData: Boolean(r.notice_data_available),
        deadline: num(r.deadline_days),
        extension: num(r.extension_days),
        median: num(r.median_days_to_file),
        p90: num(r.p90_days_to_file),
        lateBy: num(r.median_days_past_due_when_late),
        parts: 1,
      });
      continue;
    }
    c.filings += Number(r.filings ?? 0);
    c.onTime += Number(r.on_time_filings ?? 0);
    c.within += Number(r.within_extension_filings ?? 0);
    c.late += Number(r.late_filings ?? 0);
    c.notices += Number(r.late_notices ?? 0);
    c.noticeData = c.noticeData && Boolean(r.notice_data_available);
    c.parts += 1;
    c.median = c.p90 = c.lateBy = null;
  }
  return [...cells.values()]
    .map(({ parts, ...c }) => c)
    .sort((a, b) => a.form.localeCompare(b.form) || a.year - b.year || order(a.group) - order(b.group));
}

/** @param {string} group */
const order = (group) => GROUPS.findIndex(([g]) => g === group);

/** @param {Pick<Cell, "onTime" | "filings">} c */
export const share = (c) => (c.filings ? c.onTime / c.filings : null);

/**
 * The last period year whose filings are all due, extensions included, by the export's date.
 * A December year-end's 10-K is due 90 days later at most, plus 15 with a notice: mid-April.
 * So a year counts as complete from May 1 of the next.
 * @param {string} exportedAt ISO time of the export
 */
export function completeThrough(exportedAt) {
  const day = String(exportedAt).slice(0, 10);
  const year = Number(day.slice(0, 4));
  return day >= `${year}-05-01` ? year - 1 : year - 2;
}

/**
 * The on-time share each year, for one form: a line per group, from FIRST_YEAR.
 * @param {Cell[]} cells
 * @param {string} form
 */
export function series(cells, form) {
  return GROUPS.map(([group, label]) => ({
    group,
    label,
    points: cells
      .filter((c) => c.form === form && c.group === group && c.year >= FIRST_YEAR)
      .map((c) => ({ year: c.year, share: share(c), filings: c.filings })),
  }));
}

/**
 * One year's cells for one form, in group order (a group with no filings is left out).
 * @param {Cell[]} cells
 * @param {string} form
 * @param {number} year
 */
export function yearOf(cells, form, year) {
  return cells.filter((c) => c.form === form && c.year === year && c.filings > 0);
}

/**
 * The split into on time, within an extension and late: the latest complete year with notice
 * data for every group, or, until there is one, the latest year with any (to date).
 * @param {Cell[]} cells
 * @param {string} form
 * @param {number} complete
 */
export function splitYear(cells, form, complete) {
  const years = [...new Set(cells.filter((c) => c.form === form && c.year >= FIRST_YEAR).map((c) => c.year))].sort(
    (a, b) => b - a,
  );
  const known = years.filter((y) => {
    const year = yearOf(cells, form, y);
    return year.length > 0 && year.every((c) => c.noticeData);
  });
  return known.find((y) => y <= complete) ?? known[0] ?? null;
}

/**
 * @typedef {{ form: string }} State
 */
/** @type {State} */
export const DEFAULT = { form: "10-K" };

/**
 * @param {URLSearchParams} params
 * @returns {State}
 */
export function parseState(params) {
  const form = params.get("form") ?? "";
  return { form: FORMS.includes(form) ? form : DEFAULT.form };
}

/** @param {State} s */
export function toSearch(s) {
  return s.form === DEFAULT.form ? "" : `?form=${s.form}`;
}
