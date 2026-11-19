import { DEFAULT, filterRows, industries, sortRows, summarize, toRow } from "#lib/screener.js";
import { table } from "#lib/server/export.js";

/** Rows in the page's HTML: enough to read without JavaScript; the browser loads the rest. */
const FIRST = 50;

export async function load() {
  const rows = (await table("export_screener")).map(toRow);
  return {
    first: sortRows(filterRows(rows, DEFAULT), DEFAULT.sort, DEFAULT.dir).slice(0, FIRST),
    summary: summarize(rows),
    industries: industries(rows),
  };
}
