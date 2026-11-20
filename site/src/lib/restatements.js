// The restatements page: the yearly summary and the largest restatements, and what a visitor
// can choose (figure, tag switches, rate or count, kind, year, order), kept in the page's
// address. Plain functions, used when the site is built and in the browser, tested on their own.
// The kinds are dbt's (ADR 7); the page names them by what the data can see.

/** @type {[string, string][]} */
export const KINDS = [
  ["correction", "Amended (/A)"],
  ["recast", "Changed in a later filing"],
  ["tag_switch", "Tag switch"],
];
export const KIND_LABELS = Object.fromEntries(KINDS);
/** @type {[string, string][]} */
export const METRICS = [
  ["net_income", "Net income"],
  ["revenue", "Revenue"],
  ["operating_cash_flow", "Operating cash flow"],
];
export const METRIC_LABELS = Object.fromEntries(METRICS);
/** The years XBRL tagging phased in: the largest companies from 2009, all others by 2011. */
export const PHASE_IN = [2009, 2011];
/** The orders a visitor can choose for the table, and what each sorts by. */
export const ORDERS = /** @type {const} */ ({ amount: "Largest change in dollars", share: "Largest against assets", recent: "Most recent" });

/**
 * @typedef {{
 *   metric: string, tags: boolean, counts: boolean, kind: string, year: number | null,
 *   order: string
 * }} State
 */

/** @type {State} */
export const DEFAULT = { metric: "net_income", tags: false, counts: false, kind: "", year: null, order: "amount" };

/** @param {unknown} v */
const num = (v) => (v == null ? null : Number(v));
/** @param {unknown} d */
const day = (d) => (d instanceof Date ? d.toISOString().slice(0, 10) : String(d ?? "").slice(0, 10));

/**
 * One year's restatements of one figure, by kind.
 * @typedef {{
 *   year: number, reporting: number | null,
 *   kinds: Record<string, { restated: number, companies: number, days: number | null }>
 * }} Year
 */

/**
 * The yearly summary for one figure, oldest first. companies: counted once, under the first
 * kind (amendment, later filing, tag switch), so the kinds add up.
 * @param {Record<string, any>[]} rows export_restatements_by_year
 * @param {string} metric
 * @returns {Year[]}
 */
export function yearly(rows, metric) {
  /** @type {Map<number, Year>} */
  const years = new Map();
  for (const r of rows) {
    if (r.metric !== metric) continue;
    const year = Number(r.change_year);
    if (!years.has(year)) years.set(year, { year, reporting: num(r.reporting_companies), kinds: {} });
    /** @type {Year} */ (years.get(year)).kinds[r.restatement_kind] = {
      restated: Number(r.restatements ?? 0),
      companies: Number(r.companies_by_first_kind ?? 0),
      days: num(r.median_days_to_first_change),
    };
  }
  return [...years.values()].sort((a, b) => a.year - b.year);
}

/**
 * The opening: of the figures companies changed in a year (tag switches aside), the share that
 * came in an amendment; how many companies changed one, of how many reporting it; and how long
 * the median amendment took.
 * @param {Year[]} years
 * @param {number} year
 */
export function headline(years, year) {
  const y = years.find((r) => r.year === year);
  const amended = y?.kinds.correction;
  const later = y?.kinds.recast;
  const restated = (amended?.restated ?? 0) + (later?.restated ?? 0);
  return {
    year,
    share: restated ? (amended?.restated ?? 0) / restated : null,
    companies: (amended?.companies ?? 0) + (later?.companies ?? 0),
    reporting: y?.reporting ?? null,
    days: amended?.days ?? null,
  };
}

/**
 * One bar's value: companies that changed the figure that year under this kind, as a share of
 * the companies reporting it, or as a count.
 * @param {Year} y
 * @param {string} kind
 * @param {boolean} counts
 */
export function barValue(y, kind, counts) {
  const companies = y.kinds[kind]?.companies ?? 0;
  if (counts) return companies;
  return y.reporting ? companies / y.reporting : null;
}

/**
 * A row of export_restatements_largest as the page uses it.
 * @param {Record<string, any>} r
 */
export function toRestatement(r) {
  return {
    key: String(r.restatement_key),
    cik: Number(r.cik),
    name: r.company_name ?? `CIK ${r.cik}`,
    metric: r.metric,
    kind: r.restatement_kind,
    period: day(r.period_end),
    form: r.first_change_form,
    changed: day(r.first_change_at),
    year: Number(day(r.first_change_at).slice(0, 4)),
    days: num(r.days_to_first_change),
    first: num(r.first_reported_value),
    latest: num(r.latest_value),
    amount: num(r.restatement_amount),
    share: num(r.change_to_assets),
    selectedBy: r.selected_by,
  };
}
/** @typedef {ReturnType<typeof toRestatement>} Restatement */

/**
 * @param {Restatement[]} rows
 * @param {State} s
 */
export function filterRestatements(rows, s) {
  return rows.filter(
    (r) =>
      r.metric === s.metric &&
      (s.tags || r.kind !== "tag_switch") &&
      (!s.kind || r.kind === s.kind) &&
      (s.year == null || r.year === s.year),
  );
}

/**
 * @param {Restatement[]} rows
 * @param {string} order
 */
export function sortRestatements(rows, order) {
  /** @type {(r: Restatement) => number} */
  const key =
    order === "share" ? (r) => r.share ?? -1 : order === "recent" ? (r) => Date.parse(r.changed) : (r) => Math.abs(r.amount ?? 0);
  return [...rows].sort((a, b) => key(b) - key(a) || a.key.localeCompare(b.key));
}

/**
 * The visitor's choices from the page's address; anything not understood keeps its default.
 * @param {URLSearchParams} params
 * @returns {State}
 */
export function parseState(params) {
  const metric = params.get("metric") ?? "";
  const kind = params.get("kind") ?? "";
  const year = Number(params.get("year"));
  const order = params.get("order") ?? "";
  const tags = params.get("tags") === "1";
  return {
    metric: METRIC_LABELS[metric] ? metric : DEFAULT.metric,
    tags,
    counts: params.get("counts") === "1",
    kind: KIND_LABELS[kind] && (kind !== "tag_switch" || tags) ? kind : "",
    year: Number.isInteger(year) && year >= 2009 && year <= 2100 ? year : null,
    order: order in ORDERS ? order : DEFAULT.order,
  };
}

/**
 * The page's address for these choices: only what differs from the default, in a fixed order.
 * @param {State} s
 */
export function toSearch(s) {
  const params = new URLSearchParams();
  if (s.metric !== DEFAULT.metric) params.set("metric", s.metric);
  if (s.tags) params.set("tags", "1");
  if (s.counts) params.set("counts", "1");
  if (s.kind) params.set("kind", s.kind);
  if (s.year != null) params.set("year", String(s.year));
  if (s.order !== DEFAULT.order) params.set("order", s.order);
  const text = params.toString();
  return text ? `?${text}` : "";
}
