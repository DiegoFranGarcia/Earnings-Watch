import { months, summarize, toDays } from "#lib/pipeline.js";
import { table } from "#lib/server/export.js";

/** The pipeline's whole record is small (one row a day): all of it in the page. */
export async function load() {
  const days = toDays(await table("export_pipeline_health"));
  return { days, summary: summarize(days), months: months(days) };
}
