// The screener: its rows, and what a visitor can do with them (filter, sort, select an area of
// the chart), all kept in the page's address so a view can be shared. Plain functions, used when
// the site is built and in the browser, and tested on their own (tests/unit/screener.test.js).
// The overview and the company pages use the same rows and the same definitions.

/**
 * One company at its latest screened quarter, in one reporting view.
 * @typedef {{
 *   cik: number, view: string, name: string, industry: string, filer: string,
 *   quarter: string, filed: string, ni: number | null, niPrior: number | null,
 *   cash: number | null, cashPrior: number | null, assets: number | null,
 *   accruals: number | null, gap: number | null, change: number | null, growth: number | null,
 *   flagged: boolean, implausible: boolean, behind: boolean
 * }} Row
 */

/**
 * What the visitor chose. change and gap: the area selected on the chart, [from, to], or null.
 * @typedef {{
 *   view: string, q: string, industry: string, filer: string, flagged: boolean,
 *   behind: boolean, sort: string, dir: "asc" | "desc", change: number[] | null,
 *   gap: number[] | null
 * }} State
 */

export const VIEWS = ["latest", "first_reported"];
/** @type {[string, string][]} */
export const FILERS = [
  ["large_accelerated", "Large accelerated"],
  ["accelerated", "Accelerated"],
  ["non_accelerated", "Non-accelerated"],
  ["unknown", "Unknown"],
];
export const FILER_LABELS = Object.fromEntries(FILERS);
/**
 * The orders a visitor can choose, and the direction each starts in. "flagged": flagged
 * companies first, then the largest gap in dollars, which tiny asset bases cannot inflate.
 */
export const SORTS = /** @type {const} */ ({
  flagged: "desc",
  name: "asc",
  industry: "asc",
  filer: "asc",
  ni: "desc",
  change: "desc",
  cash: "desc",
  accruals: "desc",
  gap: "desc",
  quarter: "desc",
});
/** @type {State} */
export const DEFAULT = {
  view: "latest",
  q: "",
  industry: "",
  filer: "",
  flagged: false,
  behind: false,
  sort: "flagged",
  dir: "desc",
  change: null,
  gap: null,
};
/** Rows the table shows at first, and adds each time a visitor asks for more. */
export const PAGE = 100;
/** The chart's ranges, as shares of assets. Beyond them, a company is drawn (and selected) at
 * the edge, with its real value in the tooltip: one at 820% would squash every other. */
export const CHANGE_RANGE = [-1, 1];
export const GAP_RANGE = [-1, 1];
/** dbt var accrual_ratio_threshold: the gap above which a company can be flagged. */
export const GAP_THRESHOLD = 0.1;
/** A latest quarter more than this many quarters before most companies' is "behind". */
export const BEHIND_QUARTERS = 2;

/** @param {unknown} d */
const day = (d) => (d instanceof Date ? d.toISOString().slice(0, 10) : String(d ?? "").slice(0, 10));
/** @param {unknown} v */
const num = (v) => (v == null ? null : Number(v));

/** The calendar quarter a date falls in, as one number (year * 4 + quarter - 1). @param {string} d */
export const quarterIndex = (d) => Number(d.slice(0, 4)) * 4 + Math.floor((Number(d.slice(5, 7)) - 1) / 3);
/** @param {number} q */
export const quarterLabel = (q) => `Q${(q % 4) + 1} ${Math.floor(q / 4)}`;

/**
 * A row of export_screener as the site uses it ("behind" is set by prepare).
 * @param {Record<string, any>} r
 * @returns {Row}
 */
export function toRow(r) {
  const ni = num(r.ttm_net_income);
  const niPrior = num(r.prior_ttm_net_income);
  const assets = num(r.average_total_assets);
  return {
    cik: Number(r.cik),
    view: r.reporting_view,
    name: r.company_name ?? `CIK ${r.cik}`,
    industry: r.industry_group,
    filer: r.filer_group,
    quarter: day(r.period_end),
    filed: day(r.known_at),
    ni,
    niPrior,
    cash: num(r.ttm_operating_cash_flow),
    cashPrior: num(r.prior_ttm_operating_cash_flow),
    assets,
    accruals: num(r.accruals),
    gap: num(r.accruals_to_assets),
    // The chart's x-axis: defined for every company, on the same scale as the gap. Positive
    // exactly when net income rose, the flag's own test.
    change: ni != null && niPrior != null && assets ? (ni - niPrior) / assets : null,
    // Growth only means something from a positive base (shown on the company page).
    growth: ni != null && niPrior != null && niPrior > 0 ? ni / niPrior - 1 : null,
    flagged: Boolean(r.is_flagged),
    implausible: Boolean(r.is_implausible),
    behind: false,
  };
}

/**
 * The calendar quarter most companies have reported through, for the status line and for
 * "behind on filings": fiscal quarters end in every month, so the newest period in the data
 * (an August quarter-end, say) would overstate how current most of it is.
 * @param {string[]} periodEnds each company's latest period end, YYYY-MM-DD
 */
export function typicalQuarter(periodEnds) {
  if (!periodEnds.length) return { index: 0, label: "no data", newest: "" };
  const sorted = periodEnds.map(quarterIndex).sort((a, b) => b - a);
  // More than half of the companies have reported this quarter or a later one.
  const index = sorted[Math.floor(sorted.length / 2)];
  return { index, label: quarterLabel(index), newest: [...periodEnds].sort().at(-1) ?? "" };
}

/**
 * Rows ready for the pages: each marked behind on filings when its latest quarter is more than
 * BEHIND_QUARTERS before the quarter most companies have reported through (after restatements).
 * @param {Row[]} rows
 */
export function prepare(rows) {
  const through = typicalQuarter(rows.filter((r) => r.view === "latest").map((r) => r.quarter));
  for (const r of rows) r.behind = quarterIndex(r.quarter) < through.index - BEHIND_QUARTERS;
  return { rows, through };
}

/**
 * @param {number} v
 * @param {number[]} range
 */
export function clamp(v, [lo, hi]) {
  return Math.min(hi, Math.max(lo, v));
}

/** @param {string | null} text @param {number[]} limits */
function parseRange(text, limits) {
  const parts = (text ?? "").split(",").map(Number);
  if (parts.length !== 2 || !parts.every(Number.isFinite)) return null;
  const [from, to] = parts.map((p) => clamp(p, limits));
  return from < to ? [from, to] : null;
}

/**
 * The visitor's choices from the page's address; anything not understood keeps its default.
 * @param {URLSearchParams} params
 * @returns {State}
 */
export function parseState(params) {
  const sort = params.get("sort") ?? "";
  const dir = params.get("dir");
  const known = sort in SORTS;
  return {
    view: VIEWS.includes(params.get("view") ?? "") ? /** @type {string} */ (params.get("view")) : DEFAULT.view,
    q: (params.get("q") ?? "").slice(0, 80),
    industry: (params.get("industry") ?? "").slice(0, 80),
    filer: FILER_LABELS[params.get("filer") ?? ""] ? /** @type {string} */ (params.get("filer")) : "",
    flagged: params.get("flagged") === "1",
    behind: params.get("behind") === "1",
    sort: known ? sort : DEFAULT.sort,
    dir: known && (dir === "asc" || dir === "desc") ? dir : known ? SORTS[/** @type {keyof SORTS} */ (sort)] : DEFAULT.dir,
    change: parseRange(params.get("change"), CHANGE_RANGE),
    gap: parseRange(params.get("gap"), GAP_RANGE),
  };
}

/** @param {number[]} range */
const rangeText = (range) => range.map((v) => Number(v.toFixed(3))).join(",");

/**
 * The page's address for these choices: only what differs from the default, in a fixed order.
 * @param {State} s
 */
export function toSearch(s) {
  const params = new URLSearchParams();
  if (s.view !== DEFAULT.view) params.set("view", s.view);
  if (s.q.trim()) params.set("q", s.q.trim());
  if (s.industry) params.set("industry", s.industry);
  if (s.filer) params.set("filer", s.filer);
  if (s.flagged) params.set("flagged", "1");
  if (s.behind) params.set("behind", "1");
  if (s.sort !== DEFAULT.sort || s.dir !== DEFAULT.dir) {
    params.set("sort", s.sort);
    params.set("dir", s.dir);
  }
  if (s.change) params.set("change", rangeText(s.change));
  if (s.gap) params.set("gap", rangeText(s.gap));
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** @param {number} v @param {number[]} range */
const within = (v, [from, to]) => v >= from && v <= to;

/**
 * The rows that match every choice. Companies behind on filings only when asked for. A selected
 * area matches companies where they are drawn (beyond the chart's ranges, at its edge).
 * @param {Row[]} rows
 * @param {State} s
 */
export function filterRows(rows, s) {
  const q = s.q.trim().toLowerCase();
  return rows.filter(
    (r) =>
      r.view === s.view &&
      (s.behind || !r.behind) &&
      (!q || r.name.toLowerCase().includes(q) || String(r.cik) === q) &&
      (!s.industry || r.industry === s.industry) &&
      (!s.filer || r.filer === s.filer) &&
      (!s.flagged || r.flagged) &&
      (!s.change || (r.change != null && within(clamp(r.change, CHANGE_RANGE), s.change))) &&
      (!s.gap || (r.gap != null && within(clamp(r.gap, GAP_RANGE), s.gap))),
  );
}

/** @param {Row} r @param {string} key */
function value(r, key) {
  if (key === "filer") return FILER_LABELS[r.filer] ?? r.filer;
  return /** @type {Record<string, any>} */ (r)[key];
}

/**
 * @param {any} x
 * @param {any} y
 * @param {number} sign
 * @returns {number} missing values last in either direction
 */
function compare(x, y, sign) {
  if (x == null || y == null) return x != null ? -1 : y != null ? 1 : 0;
  if (x === y) return 0;
  return sign * (typeof x === "string" ? x.localeCompare(y) : x - y);
}

/**
 * Sorted copy, then by name, then by CIK. "flagged": flagged first, each group by gap in dollars.
 * @param {Row[]} rows
 * @param {string} key
 * @param {"asc" | "desc"} dir
 */
export function sortRows(rows, key, dir) {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const first =
      key === "flagged"
        ? sign * (Number(a.flagged) - Number(b.flagged)) || compare(a.accruals, b.accruals, -1)
        : compare(value(a, key), value(b, key), sign);
    return first || a.name.localeCompare(b.name) || a.cik - b.cik;
  });
}

/**
 * How many companies each view covers (up to date with filings), flags, and leaves out as
 * behind.
 * @param {Row[]} rows
 */
export function summarize(rows) {
  return Object.fromEntries(
    VIEWS.map((view) => {
      const these = rows.filter((r) => r.view === view);
      const current = these.filter((r) => !r.behind);
      return [
        view,
        {
          universe: current.length,
          flagged: current.filter((r) => r.flagged).length,
          behind: these.length - current.length,
        },
      ];
    }),
  );
}

/** @param {Row[]} rows */
export function industries(rows) {
  return [...new Set(rows.map((r) => r.industry))].sort();
}
