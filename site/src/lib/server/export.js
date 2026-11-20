// The pipeline's export, read when the site is built (prerendered): the numbers a visitor sees
// first are in the HTML itself, so they never wait for JavaScript. EW_DATA_DIR is the folder
// build_site.py assembled and verified (data/*.parquet and site.json); in CI, a fixture export.
import fs from "node:fs";
import path from "node:path";
import { asyncBufferFromFile } from "hyparquet";
import { readParquet } from "#lib/parquet.js";
import { prepare, sortRows, summarize, toRow } from "#lib/screener.js";

const DIR = process.env.EW_DATA_DIR ?? "../_site";

/** @type {Map<string, Promise<Record<string, any>[]>>} */
const tables = new Map();

/** Every row of one exported table, read once per build. @param {string} name */
export function table(name) {
  if (!tables.has(name)) {
    const file = path.join(DIR, "data", `${name}.parquet`);
    if (!fs.existsSync(file)) {
      throw new Error(`${file} is missing: set EW_DATA_DIR to an export (build_site.py's output)`);
    }
    tables.set(name, asyncBufferFromFile(file).then(readParquet));
  }
  return /** @type {Promise<Record<string, any>[]>} */ (tables.get(name));
}

/** Which export this build shows: run, time, commit (site.json, written by build_site.py). */
export function liveExport() {
  const file = path.join(DIR, "site.json");
  if (!fs.existsSync(file)) throw new Error(`${file} is missing: set EW_DATA_DIR to an export`);
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

/** @param {Date | string} d */
const iso = (d) => (d instanceof Date ? d.toISOString().slice(0, 10) : String(d).slice(0, 10));

/** @type {Promise<ReturnType<typeof prepare>> | undefined} */
let screener;

/** The screener's rows, each marked behind on filings or not, and the quarter that is judged by. */
export function screenerRows() {
  screener ??= table("export_screener").then((rows) => prepare(rows.map(toRow)));
  return screener;
}

/** What every page's status line says: how fresh the data is. */
export async function status() {
  const { through } = await screenerRows();
  const live = liveExport();
  return { exported_at: live.exported_at, commit: live.commit, through: through.label, newest: through.newest };
}

/**
 * Each company's quarters, oldest first, from export_company_quarters.
 * @type {Promise<Map<number, Record<string, any>[]>> | undefined}
 */
let quartersByCompany;

function companyQuarters() {
  quartersByCompany ??= table("export_company_quarters").then((rows) => {
    /** @type {Map<number, Record<string, any>[]>} */
    const by = new Map();
    for (const q of rows) {
      if (!by.has(q.cik)) by.set(q.cik, []);
      /** @type {Record<string, any>[]} */ (by.get(q.cik)).push(q);
    }
    for (const list of by.values()) list.sort((a, b) => (iso(a.period_end) < iso(b.period_end) ? -1 : 1));
    return by;
  });
  return quartersByCompany;
}

/** Everything the overview shows, computed once at build time. */
export async function overview() {
  const [{ rows: all }, byCompany, health] = await Promise.all([
    screenerRows(),
    companyQuarters(),
    table("export_pipeline_health"),
  ]);
  const summary = summarize(all);

  // The flagged companies up to date with their filings, largest gap in dollars first, each with
  // its last eight quarters of net income in the same view.
  const rows = sortRows(
    all.filter((r) => r.flagged && !r.behind),
    "accruals",
    "desc",
  ).map((r) => {
    const field = r.view === "latest" ? "net_income_latest" : "net_income_first_reported";
    const series = (byCompany.get(r.cik) ?? [])
      .filter((q) => iso(q.period_end) <= r.quarter)
      .slice(-8)
      .map((q) => q[field])
      .filter((v) => v != null);
    return {
      cik: r.cik,
      view: r.view,
      name: r.name,
      industry: r.industry,
      quarter: r.quarter,
      net_income: r.ni,
      net_income_prior: r.niPrior,
      cash: r.cash,
      cash_prior: r.cashPrior,
      gap: r.gap,
      implausible: r.implausible,
      series,
    };
  });

  const ran = health.filter((d) => d.dbt_invocations > 0).sort((a, b) => (iso(a.date_day) < iso(b.date_day) ? 1 : -1));
  const last = ran[0];
  return {
    summary,
    rows,
    industries: [...new Set(rows.map((r) => r.industry))].sort(),
    pipeline: {
      last_run_day: last ? iso(last.date_day) : null,
      tests_passed: last?.tests_passed ?? null,
      tests_failed: last?.tests_failed ?? null,
      days_with_runs: ran.length,
      // Snowflake and EMR only (mart_pipeline_costs), over the 30 days the export covers.
      dollars_30d: health.reduce((sum, d) => sum + (d.dollars ?? 0), 0),
    },
  };
}

/** Every company with a page: its CIK, name, and whether it is flagged or behind (latest view). */
export async function companyList() {
  const { rows } = await screenerRows();
  return sortRows(
    rows.filter((r) => r.view === "latest"),
    "name",
    "asc",
  ).map((r) => ({ cik: r.cik, name: r.name, flagged: r.flagged, behind: r.behind }));
}

/** @param {any} v */
const plain = (v) => (v == null ? null : Number(v));

/**
 * One company's page: its screener rows in both views, its quarters, its history, and any of
 * the largest restatements that are its own. Null if the screener does not cover it.
 * @param {number} cik
 */
export async function company(cik) {
  const [{ rows }, byCompany, history, largest] = await Promise.all([
    screenerRows(),
    companyQuarters(),
    table("export_company_history"),
    table("export_restatements_largest"),
  ]);
  const views = Object.fromEntries(rows.filter((r) => r.cik === cik).map((r) => [r.view, r]));
  if (!views.latest && !views.first_reported) return null;
  return {
    views,
    quarters: (byCompany.get(cik) ?? []).map((q) => ({
      end: iso(q.period_end),
      fiscal: q.fiscal_year && q.fiscal_quarter ? `FY${q.fiscal_year} Q${q.fiscal_quarter}` : "",
      niFirst: plain(q.net_income_first_reported),
      niLatest: plain(q.net_income_latest),
      cashFirst: plain(q.operating_cash_flow_first_reported),
      cashLatest: plain(q.operating_cash_flow_latest),
      niRestated: Boolean(q.is_net_income_restated),
      cashRestated: Boolean(q.is_operating_cash_flow_restated),
      derived: Boolean(q.is_derived),
    })),
    history: history
      .filter((h) => h.cik === cik)
      .sort((a, b) => a.version_number - b.version_number)
      .map((h) => ({
        from: iso(h.valid_from),
        to: h.valid_to ? iso(h.valid_to) : null,
        name: h.company_name,
        industry: h.industry_title,
        filer: h.filer_status,
      })),
    restatements: largest
      .filter((r) => r.cik === cik)
      .sort((a, b) => (iso(a.period_end) < iso(b.period_end) ? 1 : -1))
      .map((r) => ({
        metric: r.metric,
        end: iso(r.period_end),
        kind: r.restatement_kind,
        form: r.first_change_form,
        days: r.days_to_first_change,
        first: plain(r.first_reported_value),
        latest: plain(r.latest_value),
        pct: plain(r.restatement_pct),
      })),
  };
}
