import { DEFAULT, METRIC_LABELS, filterRestatements, sortRestatements, toRestatement } from "#lib/restatements.js";
import { liveExport, screenerRows, table } from "#lib/server/export.js";

/** Rows in the page's HTML: enough to read without JavaScript; the browser loads the rest. */
const FIRST = 50;

export async function load() {
  const [byYear, largest, { rows }] = await Promise.all([
    table("export_restatements_by_year"),
    table("export_restatements_largest"),
    screenerRows(),
  ]);
  const all = largest.map(toRestatement);
  const screened = new Set(rows.map((r) => r.cik));
  return {
    // The yearly summary for the three figures the page shows, only the columns it reads.
    byYear: byYear
      .filter((r) => METRIC_LABELS[r.metric])
      .map((r) => ({
        change_year: r.change_year,
        restatement_kind: r.restatement_kind,
        metric: r.metric,
        restatements: r.restatements,
        companies_by_first_kind: r.companies_by_first_kind,
        reporting_companies: r.reporting_companies,
        median_days_to_first_change: r.median_days_to_first_change,
      })),
    first: sortRestatements(filterRestatements(all, DEFAULT), DEFAULT.order).slice(0, FIRST),
    // Companies in the table that have a page of their own; the others link to EDGAR.
    screened: [...new Set(all.map((r) => r.cik))].filter((cik) => screened.has(cik)),
    // The opening's year: the last full year before the export.
    fullYear: Number(String(liveExport().exported_at).slice(0, 4)) - 1,
  };
}
