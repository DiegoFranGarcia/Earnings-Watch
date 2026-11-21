// The SQL page's logic, apart from DuckDB itself: the example queries, the shareable link (the
// query lives in the address's fragment, which never reaches a server), how results are shown and
// downloaded (both capped), and errors in plain words. Plain functions, tested on their own.

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

/**
 * What went wrong, in plain words, keeping DuckDB's own message for the details.
 * @param {unknown} error
 * @returns {{ kind: "memory" | "extension" | "sql", text: string, detail: string }}
 */
export function describeError(error) {
  const detail = String(error instanceof Error ? error.message : error).trim();
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
