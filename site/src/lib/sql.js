// The SQL page's logic, apart from DuckDB itself: the example queries, the shareable link (the
// query lives in the address's fragment, which never reaches a server), downloading the tables
// and checking each against site.json, how results are shown and downloaded (both capped), and
// errors in plain words. Plain functions, tested on their own.

/** Rows shown on the page; the full count is always reported. */
export const ROW_CAP = 1000;
/** Rows a CSV download holds at most: a cross join can produce millions. */
export const CSV_CAP = 100_000;

/**
 * Ready-made queries that tell the project's stories. Each runs against the fixture export in the
 * site's browser tests, so a renamed column breaks the build, not the demo.
 * @type {{ id: string, title: string, about: string, sql: string }[]}
 */
export const EXAMPLES = [
  {
    id: "flagged",
    title: "Flagged companies, largest gap first",
    about: "Rising net income that operating cash flow does not back up, after restatements.",
    sql: `select
  company_name,
  industry_group,
  round(accruals / 1e6, 1) as gap_millions,
  round(100 * accruals_to_assets, 1) as gap_pct_of_assets
from export_screener
where reporting_view = 'latest' and is_flagged
order by accruals desc
limit 25`,
  },
  {
    id: "units",
    title: "Figures that look like units mistakes",
    about: "A year's net income or cash flow above twice the company's assets: usually thousands tagged as units.",
    sql: `select
  company_name,
  period_end,
  round(ttm_net_income / 1e6, 1) as net_income_millions,
  round(average_total_assets / 1e6, 1) as assets_millions,
  round(ttm_net_income / nullif(average_total_assets, 0), 1) as times_assets
from export_screener
where reporting_view = 'latest' and is_implausible
order by abs(ttm_net_income / nullif(average_total_assets, 0)) desc`,
  },
  {
    id: "amended",
    title: "Changed net income: amended, or changed in a later filing",
    about: "Each year's restated figures by how the change arrived (tag switches aside).",
    sql: `select
  change_year,
  sum(restatements) filter (where restatement_kind = 'correction') as amended,
  sum(restatements) filter (where restatement_kind = 'recast') as changed_later,
  round(100 * amended / nullif(amended + changed_later, 0), 1) as pct_amended
from export_restatements_by_year
where metric = 'net_income'
group by change_year
order by change_year desc`,
  },
  {
    id: "on-time",
    title: "10-Ks filed by the deadline, by filer group",
    about: "DuckDB's PIVOT: one column per filer group, each against its own deadline.",
    sql: `pivot (
  select period_year, filer_group, round(100 * on_time_share, 1) as pct_on_time
  from export_filing_timeliness
  where form = '10-K'
)
on filer_group using first(pct_on_time)
order by period_year desc`,
  },
  {
    id: "restated-quarters",
    title: "Companies with the most restated quarters",
    about: "Quarters whose net income a later filing changed, joined to the screener for names.",
    sql: `select s.company_name, count(*) as restated_quarters
from export_company_quarters as q
join export_screener as s on s.cik = q.cik and s.reporting_view = 'latest'
where q.is_net_income_restated
group by s.company_name
order by restated_quarters desc
limit 20`,
  },
  {
    id: "pipeline",
    title: "The pipeline's last 30 days",
    about: "Tests and volume checks each day, and what Snowflake and EMR cost.",
    sql: `select date_day, tests_passed, tests_warned, tests_failed, volume_failures, round(dollars, 2) as dollars
from export_pipeline_health
order by date_day desc`,
  },
];

const FRAGMENT = "sql=";

/** The address fragment that carries a query: never sent to a server, no length limit. */
export const toFragment = (/** @type {string} */ sql) => (sql.trim() ? `#${FRAGMENT}${encodeURIComponent(sql)}` : "");

/** The query in an address fragment, or "" when there is none or it cannot be read. */
export function fromFragment(/** @type {string} */ hash) {
  const body = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!body.startsWith(FRAGMENT)) return "";
  try {
    return decodeURIComponent(body.slice(FRAGMENT.length));
  } catch {
    return "";
  }
}

/** @param {number} n */
const pad = (n, width = 2) => String(n).padStart(width, "0");

/**
 * One value as text, by its Arrow type: dates as YYYY-MM-DD and timestamps in UTC, 64-bit
 * integers exactly (BigInt), nulls empty. Decimals arrive as doubles (castDecimalToDouble).
 * @param {unknown} value
 * @param {string} type String(field.type), e.g. "Date32<DAY>", "Timestamp<MICROSECOND>"
 */
export function formatValue(value, type) {
  if (value == null) return "";
  if (type.startsWith("Date") && typeof value === "number") return new Date(value).toISOString().slice(0, 10);
  if (type.startsWith("Timestamp") && typeof value === "number") {
    return new Date(value).toISOString().replace("T", " ").replace(/\.000Z$|Z$/, "");
  }
  if (type.startsWith("Time") && typeof value === "bigint") {
    const seconds = Number(value / 1_000_000n);
    return `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor(seconds / 60) % 60)}:${pad(seconds % 60)}`;
  }
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Math.round(value * 1e6) / 1e6);
  return String(value);
}

/**
 * A CSV of the rows (RFC 4180 quoting). A cell a spreadsheet would run as a formula (starting
 * with an equals, plus, minus or at sign, and not a number) gets a leading apostrophe.
 * @param {string[]} columns
 * @param {string[][]} rows already formatted
 */
export function toCsv(columns, rows) {
  /** @param {string} cell */
  const quote = (cell) => {
    const safe = /^[=+\-@]/.test(cell) && Number.isNaN(Number(cell)) ? `'${cell}` : cell;
    return /[",\r\n]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
  };
  return [columns, ...rows].map((row) => row.map(quote).join(",")).join("\r\n") + "\r\n";
}

/** The site's data changed while the page was open, or a cache held part of the previous copy. */
export class StaleDataError extends Error {
  /** @param {string} message */
  constructor(message) {
    super(message);
    this.name = "StaleDataError";
  }
}

/** A file could not be downloaded at all (offline, or the server refused). */
export class DownloadError extends Error {
  /** @param {string} message */
  constructor(message) {
    super(message);
    this.name = "DownloadError";
  }
}

/**
 * A table's file, tagged with the export it belongs to: a new export has new addresses, so no
 * cache, the browser's or GitHub's, can answer with a copy from an earlier one.
 * @param {string} siteRoot the site's absolute URL, ending in "/"
 * @param {string} table
 * @param {string} runId the export's run ID (site.json)
 */
export const tableUrl = (siteRoot, table, runId) =>
  new URL(`data/${table}.parquet?v=${encodeURIComponent(runId)}`, siteRoot).href;

/** @param {Uint8Array} bytes */
export async function sha256Hex(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", /** @type {BufferSource} */ (bytes)));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * The file must be exactly the one site.json lists, or nothing is queried: a stale copy would
 * otherwise mix an old table into answers about new ones.
 * @param {string} table
 * @param {Uint8Array} bytes
 * @param {{ bytes?: number, sha256?: string } | undefined} entry site.json's entry for the file
 */
export async function checkTable(table, bytes, entry) {
  if (!entry?.sha256) throw new StaleDataError(`${table}.parquet is not in this site's site.json`);
  const digest = await sha256Hex(bytes);
  if (bytes.byteLength !== entry.bytes || digest !== entry.sha256) {
    throw new StaleDataError(
      `${table}.parquet is ${bytes.byteLength} bytes with sha256 ${digest.slice(0, 12)}, ` +
        `but site.json lists ${entry.bytes} bytes with sha256 ${entry.sha256.slice(0, 12)}`,
    );
  }
}

/**
 * Fetch, turning a network failure or an HTTP error into a DownloadError.
 * @param {typeof fetch} fetchFn
 * @param {string} url
 * @param {RequestInit} [init]
 */
async function get(fetchFn, url, init) {
  let response;
  try {
    response = await fetchFn(url, init);
  } catch (error) {
    throw new DownloadError(`${url}: ${error instanceof Error ? error.message : error}`);
  }
  if (!response.ok) throw new DownloadError(`${url}: HTTP ${response.status}`);
  return response;
}

/**
 * Every table, whole, in one request each, checked against the live site.json (ADR 20). Byte
 * ranges would read a file in several requests, and right after a deploy a cache can answer some
 * of them from the previous export (2026-11-21); a whole file is also what a sha256 check needs.
 * site.json is fetched past the browser's cache: it says which export is live.
 * @param {string} siteRoot the site's absolute URL, ending in "/"
 * @param {string[]} tables
 * @param {typeof fetch} [fetchFn]
 * @returns {Promise<[string, Uint8Array][]>}
 */
export async function downloadTables(siteRoot, tables, fetchFn = fetch) {
  const live = await (await get(fetchFn, new URL("site.json", siteRoot).href, { cache: "no-store" })).json();
  const runId = live?.run_id ?? live?.exported_at;
  if (typeof runId !== "string" || !live.files) throw new StaleDataError("site.json names no export");
  return Promise.all(
    tables.map(async (table) => {
      const response = await get(fetchFn, tableUrl(siteRoot, table, runId));
      const bytes = new Uint8Array(await response.arrayBuffer());
      await checkTable(table, bytes, live.files[`${table}.parquet`]);
      return /** @type {[string, Uint8Array]} */ ([table, bytes]);
    }),
  );
}

/**
 * What went wrong, in plain words, keeping the original message for the details.
 * @param {unknown} error
 * @returns {{ kind: "stale" | "download" | "memory" | "extension" | "sql", text: string, detail: string }}
 */
export function describeError(error) {
  const detail = String(error instanceof Error ? error.message : error).trim();
  if (error instanceof StaleDataError) {
    return {
      kind: "stale",
      text: "The site's data was updated while this page was open, so your browser holds part of the previous copy. Reload the page to use the new data.",
      detail,
    };
  }
  if (error instanceof DownloadError) {
    return {
      kind: "download",
      text: "A data file could not be downloaded. Check your connection, then run again.",
      detail,
    };
  }
  if (/out of memory|memory access out of bounds|could not allocate|Aborted\(OOM\)|RangeError: Array buffer allocation/i.test(detail)) {
    return {
      kind: "memory",
      text: "Your browser ran out of memory for this query. Phones have far less room than laptops: add a LIMIT, filter first, or select fewer columns.",
      detail,
    };
  }
  if (/extension/i.test(detail) && /(not found|failed to (download|load|install)|could not load|HTTP)/i.test(detail)) {
    return {
      kind: "extension",
      text: "That needs a DuckDB extension this console does not include: it has Parquet only, served from this site.",
      detail,
    };
  }
  return { kind: "sql", text: detail.split("\n")[0], detail };
}
