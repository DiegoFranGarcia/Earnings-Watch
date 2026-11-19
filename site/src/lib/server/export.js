// The pipeline's export, read when the site is built (prerendered): the numbers a visitor sees
// first are in the HTML itself, so they never wait for JavaScript. EW_DATA_DIR is the folder
// build_site.py assembled and verified (data/*.parquet and site.json); in CI, a fixture export.
import fs from "node:fs";
import path from "node:path";
import { asyncBufferFromFile, parquetReadObjects } from "hyparquet";
import { compressors } from "hyparquet-compressors";

const DIR = process.env.EW_DATA_DIR ?? "../_site";

/** @type {Map<string, Promise<Record<string, any>[]>>} */
const tables = new Map();

/** Every row of one exported table, with 64-bit integers as plain numbers. @param {string} name */
export function table(name) {
  if (!tables.has(name)) {
    const file = path.join(DIR, "data", `${name}.parquet`);
    if (!fs.existsSync(file)) {
      throw new Error(`${file} is missing: set EW_DATA_DIR to an export (build_site.py's output)`);
    }
    tables.set(
      name,
      asyncBufferFromFile(file)
        .then((buffer) => parquetReadObjects({ file: buffer, compressors }))
        .then((rows) =>
          rows.map((row) =>
            Object.fromEntries(
              Object.entries(row).map(([k, v]) => [k, typeof v === "bigint" ? Number(v) : v]),
            ),
          ),
        ),
    );
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

/** What every page's status line says: how fresh the data is. */
export async function status() {
  const screener = await table("export_screener");
  const live = liveExport();
  const through = screener.reduce((m, r) => (iso(r.period_end) > m ? iso(r.period_end) : m), "");
  return { exported_at: live.exported_at, commit: live.commit, data_through: through };
}

/** Everything the overview shows, computed once at build time. */
export async function overview() {
  const [screener, quarters, health] = await Promise.all([
    table("export_screener"),
    table("export_company_quarters"),
    table("export_pipeline_health"),
  ]);

  const views = /** @type {const} */ (["latest", "first_reported"]);
  const summary = Object.fromEntries(
    views.map((view) => {
      const rows = screener.filter((r) => r.reporting_view === view);
      return [view, { universe: rows.length, flagged: rows.filter((r) => r.is_flagged).length }];
    }),
  );

  // Each flagged company's last eight quarters of net income, in the same view.
  const flagged = screener.filter((r) => r.is_flagged);
  const wanted = new Set(flagged.map((r) => r.cik));
  /** @type {Map<number, Record<string, any>[]>} */
  const byCompany = new Map();
  for (const q of quarters) {
    if (!wanted.has(q.cik)) continue;
    if (!byCompany.has(q.cik)) byCompany.set(q.cik, []);
    /** @type {Record<string, any>[]} */ (byCompany.get(q.cik)).push(q);
  }
  const rows = flagged
    .map((r) => {
      const field = r.reporting_view === "latest" ? "net_income_latest" : "net_income_first_reported";
      const series = (byCompany.get(r.cik) ?? [])
        .filter((q) => iso(q.period_end) <= iso(r.period_end))
        .sort((a, b) => (iso(a.period_end) < iso(b.period_end) ? -1 : 1))
        .slice(-8)
        .map((q) => q[field])
        .filter((v) => v != null);
      return {
        cik: r.cik,
        view: r.reporting_view,
        name: r.company_name ?? `CIK ${r.cik}`,
        industry: r.industry_group,
        filer_group: r.filer_group,
        quarter: iso(r.period_end),
        net_income: r.ttm_net_income,
        net_income_prior: r.prior_ttm_net_income,
        cash: r.ttm_operating_cash_flow,
        cash_prior: r.prior_ttm_operating_cash_flow,
        gap: r.accruals_to_assets,
        series,
      };
    })
    .sort((a, b) => b.gap - a.gap);

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
