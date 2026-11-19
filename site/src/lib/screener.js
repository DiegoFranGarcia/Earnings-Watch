// The screener: its rows, and what a visitor can do with them (filter, sort, select an area of
// the chart), all kept in the page's address so a view can be shared. Plain functions, used when
// the site is built and in the browser, and tested on their own (tests/unit/screener.test.js).

/**
 * One company at its latest screened quarter, in one reporting view.
 * @typedef {{
 *   cik: number, view: string, name: string, industry: string, filer: string, quarter: string,
 *   ni: number | null, niPrior: number | null, cash: number | null, cashPrior: number | null,
 *   gap: number | null, flagged: boolean, growth: number | null
 * }} Row
 */

/**
 * What the visitor chose. growth and gap: the area selected on the chart, [from, to], or null.
 * @typedef {{
 *   view: string, q: string, industry: string, filer: string, flagged: boolean,
 *   sort: string, dir: "asc" | "desc", growth: number[] | null, gap: number[] | null
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
/** The columns a visitor can sort by, and the direction each starts in. */
export const SORTS = /** @type {const} */ ({
  name: "asc",
  industry: "asc",
  filer: "asc",
  ni: "desc",
  growth: "desc",
  cash: "desc",
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
  sort: "gap",
  dir: "desc",
  growth: null,
  gap: null,
};
/** Rows the table shows at first, and adds each time a visitor asks for more. */
export const PAGE = 100;
/** The chart's fixed ranges. A company beyond them is drawn, and selected, at the edge. */
export const GROWTH_RANGE = [-1, 4];
export const GAP_RANGE = [-0.5, 0.5];
/** dbt var accrual_ratio_threshold: the gap above which a company can be flagged. */
export const GAP_THRESHOLD = 0.1;

/** @param {unknown} d */
const day = (d) => (d instanceof Date ? d.toISOString().slice(0, 10) : String(d).slice(0, 10));
/** @param {unknown} v */
const num = (v) => (v == null ? null : Number(v));

/**
 * A row of export_screener as the screener uses it.
 * @param {Record<string, any>} r
 * @returns {Row}
 */
export function toRow(r) {
  const ni = num(r.ttm_net_income);
  const niPrior = num(r.prior_ttm_net_income);
  return {
    cik: Number(r.cik),
    view: r.reporting_view,
    name: r.company_name ?? `CIK ${r.cik}`,
    industry: r.industry_group,
    filer: r.filer_group,
    quarter: day(r.period_end),
    ni,
    niPrior,
    cash: num(r.ttm_operating_cash_flow),
    cashPrior: num(r.prior_ttm_operating_cash_flow),
    gap: num(r.accruals_to_assets),
    flagged: Boolean(r.is_flagged),
    // Growth only means something from a positive base.
    growth: ni != null && niPrior != null && niPrior > 0 ? ni / niPrior - 1 : null,
  };
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
    sort: known ? sort : DEFAULT.sort,
    dir: known && (dir === "asc" || dir === "desc") ? dir : known ? SORTS[/** @type {keyof SORTS} */ (sort)] : DEFAULT.dir,
    growth: parseRange(params.get("growth"), GROWTH_RANGE),
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
  if (s.sort !== DEFAULT.sort || s.dir !== DEFAULT.dir) {
    params.set("sort", s.sort);
    params.set("dir", s.dir);
  }
  if (s.growth) params.set("growth", rangeText(s.growth));
  if (s.gap) params.set("gap", rangeText(s.gap));
  const text = params.toString();
  return text ? `?${text}` : "";
}

/**
 * The rows that match every choice. A selected area matches only companies on the chart: those
 * with a growth figure, at the place they are drawn (beyond the chart's ranges, at its edge).
 * @param {Row[]} rows
 * @param {State} s
 */
export function filterRows(rows, s) {
  const q = s.q.trim().toLowerCase();
  return rows.filter(
    (r) =>
      r.view === s.view &&
      (!q || r.name.toLowerCase().includes(q) || String(r.cik) === q) &&
      (!s.industry || r.industry === s.industry) &&
      (!s.filer || r.filer === s.filer) &&
      (!s.flagged || r.flagged) &&
      (!s.growth || (r.growth != null && within(clamp(r.growth, GROWTH_RANGE), s.growth))) &&
      (!s.gap || (r.gap != null && within(clamp(r.gap, GAP_RANGE), s.gap))),
  );
}

/** @param {number} v @param {number[]} range */
const within = (v, [from, to]) => v >= from && v <= to;

/** @param {Row} r @param {string} key */
function value(r, key) {
  if (key === "filer") return FILER_LABELS[r.filer] ?? r.filer;
  return /** @type {Record<string, any>} */ (r)[key];
}

/**
 * Sorted copy: missing values last in either direction, then by name, then by CIK.
 * @param {Row[]} rows
 * @param {string} key
 * @param {"asc" | "desc"} dir
 */
export function sortRows(rows, key, dir) {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = value(a, key);
    const y = value(b, key);
    if (x == null || y == null) {
      if (x != null) return -1;
      if (y != null) return 1;
    } else if (x !== y) {
      return sign * (typeof x === "string" ? x.localeCompare(y) : x - y);
    }
    return a.name.localeCompare(b.name) || a.cik - b.cik;
  });
}

/**
 * How many companies each view screens, and flags.
 * @param {Row[]} rows
 */
export function summarize(rows) {
  return Object.fromEntries(
    VIEWS.map((view) => {
      const these = rows.filter((r) => r.view === view);
      return [view, { universe: these.length, flagged: these.filter((r) => r.flagged).length }];
    }),
  );
}

/** @param {Row[]} rows */
export function industries(rows) {
  return [...new Set(rows.map((r) => r.industry))].sort();
}

/**
 * The calendar quarter most companies have reported through, for the status line: fiscal
 * quarters end in every month, so the newest period in the data (an August quarter-end, say)
 * would overstate how current most of it is.
 * @param {string[]} periodEnds each company's latest period end, YYYY-MM-DD
 */
export function typicalQuarter(periodEnds) {
  if (!periodEnds.length) return { label: "no data", newest: "" };
  const index = (/** @type {string} */ d) => Number(d.slice(0, 4)) * 4 + Math.floor((Number(d.slice(5, 7)) - 1) / 3);
  const sorted = periodEnds.map(index).sort((a, b) => b - a);
  // More than half of the companies have reported this quarter or a later one.
  const q = sorted[Math.floor(sorted.length / 2)];
  return {
    label: `Q${(q % 4) + 1} ${Math.floor(q / 4)}`,
    newest: [...periodEnds].sort().at(-1) ?? "",
  };
}
