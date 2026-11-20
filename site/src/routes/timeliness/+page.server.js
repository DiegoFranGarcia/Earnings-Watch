import { completeThrough, toCells } from "#lib/timeliness.js";
import { liveExport, table } from "#lib/server/export.js";

/** The whole table is small (three groups, two forms, one row a year): all of it in the page. */
export async function load() {
  const rows = await table("export_filing_timeliness");
  return {
    cells: toCells(rows),
    // The last period year whose filings were all due when the export ran.
    complete: completeThrough(String(liveExport().exported_at)),
  };
}
