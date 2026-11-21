// The SQL page's logic and its policy change, on their own: node --test, no browser.
import assert from "node:assert/strict";
import { test } from "node:test";
import { allowWasm } from "../../scripts/sql-csp.mjs";
import { createHash } from "node:crypto";
import {
  DownloadError,
  EXAMPLES,
  StaleDataError,
  checkTable,
  describeError,
  downloadTables,
  formatValue,
  fromFragment,
  tableUrl,
  toCsv,
  toFragment,
} from "#lib/sql.js";

test("a query travels in the fragment, round-trips exactly, and nothing else is read as one", () => {
  const sql = "select 'a b', 1 + 1 as two -- #note\nfrom export_screener where x = '100%'";
  assert.equal(fromFragment(toFragment(sql)), sql);
  assert.ok(toFragment(sql).startsWith("#sql="));
  assert.equal(toFragment("   "), "");
  assert.equal(fromFragment(""), "");
  assert.equal(fromFragment("#other=1"), "");
  assert.equal(fromFragment("#sql=%E0%A4%A"), ""); // malformed: ignored, not thrown
});

test("values show as people read them: dates, UTC times, exact big integers, empty nulls", () => {
  assert.equal(formatValue(Date.UTC(2026, 0, 2), "Date32<DAY>"), "2026-01-02");
  assert.equal(formatValue(Date.UTC(2026, 0, 2, 3, 4, 5, 123), "Timestamp<MICROSECOND>"), "2026-01-02 03:04:05.123");
  assert.equal(formatValue(Date.UTC(2026, 0, 2, 3, 4, 5), "Timestamp<MICROSECOND>"), "2026-01-02 03:04:05");
  assert.equal(formatValue(9007199254740993n, "Int64"), "9007199254740993");
  assert.equal(formatValue(3723000000n, "Time64<MICROSECOND>"), "01:02:03");
  assert.equal(formatValue(0.1 + 0.2, "Float64"), "0.3");
  assert.equal(formatValue(null, "Utf8"), "");
  assert.equal(formatValue(true, "Bool"), "true");
});

test("CSV: quoted where needed, and a cell a spreadsheet would run is defused", () => {
  const csv = toCsv(["name", "note"], [["Acme, Inc.", 'said "hi"'], ["=HYPERLINK(1)", "-12.5"], ["@x", "line\nbreak"]]);
  assert.equal(
    csv,
    'name,note\r\n"Acme, Inc.","said ""hi"""\r\n\'=HYPERLINK(1),-12.5\r\n\'@x,"line\nbreak"\r\n',
  );
});

test("errors in plain words: memory, a missing extension, or DuckDB's own first line", () => {
  assert.equal(describeError(new Error("Out of Memory Error: could not allocate block")).kind, "memory");
  assert.equal(describeError(new RangeError("RangeError: Array buffer allocation failed")).kind, "memory");
  const ext = describeError("IO Error: Extension http://x/duckdb/v1.4.3/wasm_eh/json.duckdb_extension.wasm is not available");
  assert.equal(ext.kind, "extension");
  const sql = describeError(new Error('Binder Error: Referenced column "nope" not found\nLINE 1: ...'));
  assert.deepEqual([sql.kind, sql.text], ["sql", 'Binder Error: Referenced column "nope" not found']);
});

test("the examples have unique ids and read only exported tables", () => {
  assert.equal(new Set(EXAMPLES.map((e) => e.id)).size, EXAMPLES.length);
  for (const e of EXAMPLES) assert.match(e.sql, /\bexport_[a-z_]+\b/, e.id);
});

test("the SQL page's policy gains exactly 'wasm-unsafe-eval' and worker-src 'self'", () => {
  const site = "default-src 'self'; connect-src 'self'; script-src 'self' 'sha256-abc'; style-src 'self' 'unsafe-inline'; base-uri 'none'";
  assert.equal(
    allowWasm(site),
    "default-src 'self'; connect-src 'self'; script-src 'self' 'sha256-abc' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self' 'unsafe-inline'; base-uri 'none'",
  );
  assert.throws(() => allowWasm(allowWasm(site)), /fresh build/);
  assert.throws(() => allowWasm("default-src 'self'"), /no script-src/);
});

const ROOT = "https://example.test/Earnings-Watch/";
const bytesOf = (/** @type {string} */ text) => new TextEncoder().encode(text);
const entryOf = (/** @type {Uint8Array} */ b) => ({ bytes: b.byteLength, sha256: createHash("sha256").update(b).digest("hex") });

test("a table's address names the export it belongs to, safely encoded", () => {
  assert.equal(
    tableUrl(ROOT, "export_screener", "asset_triggered__2026-11-21T13:58:12+00:00_x"),
    "https://example.test/Earnings-Watch/data/export_screener.parquet?v=asset_triggered__2026-11-21T13%3A58%3A12%2B00%3A00_x",
  );
});

test("a table is used only if its size and sha256 are exactly site.json's", async () => {
  const file = bytesOf("PAR1 the table PAR1");
  await checkTable("t", file, entryOf(file));
  await assert.rejects(checkTable("t", file, { ...entryOf(file), sha256: "0".repeat(64) }), StaleDataError);
  await assert.rejects(checkTable("t", file, { ...entryOf(file), bytes: 1 }), StaleDataError);
  await assert.rejects(checkTable("t", file, undefined), /not in this site's site.json/);
});

/**
 * A fetch that serves the given files and records each request.
 * @param {Record<string, Uint8Array | number>} files path (after the site root) -> body, or an HTTP status
 */
function fakeFetch(files) {
  /** @type {{ url: string, init: RequestInit | undefined }[]} */
  const calls = [];
  /** @type {typeof fetch} */
  const fetchFn = async (input, init) => {
    const url = String(input);
    calls.push({ url, init });
    const body = files[url.slice(ROOT.length)];
    if (body === undefined) return new Response("404", { status: 404 });
    if (typeof body === "number") return new Response("", { status: body });
    return new Response(/** @type {BodyInit} */ (body), { status: 200 });
  };
  return { fetchFn, calls };
}

test("downloadTables: site.json past the cache, then every table whole at its export's address", async () => {
  const a = bytesOf("table a"), b = bytesOf("table b");
  const live = { run_id: "run-1", files: { "a.parquet": entryOf(a), "b.parquet": entryOf(b) } };
  const { fetchFn, calls } = fakeFetch({
    "site.json": bytesOf(JSON.stringify(live)),
    "data/a.parquet?v=run-1": a,
    "data/b.parquet?v=run-1": b,
  });
  const files = await downloadTables(ROOT, ["a", "b"], fetchFn);
  assert.deepEqual(files.map(([name, data]) => [name, new TextDecoder().decode(data)]), [["a", "table a"], ["b", "table b"]]);
  assert.equal(calls[0].url, `${ROOT}site.json`);
  assert.equal(calls[0].init?.cache, "no-store");
  for (const call of calls.slice(1)) assert.equal(new Headers(call.init?.headers).get("range"), null);
});

test("downloadTables: a mismatch is stale data, a refused file is a download error", async () => {
  const a = bytesOf("table a");
  const live = { run_id: "run-1", files: { "a.parquet": { ...entryOf(a), sha256: "f".repeat(64) } } };
  const stale = fakeFetch({ "site.json": bytesOf(JSON.stringify(live)), "data/a.parquet?v=run-1": a });
  await assert.rejects(downloadTables(ROOT, ["a"], stale.fetchFn), StaleDataError);
  const refused = fakeFetch({ "site.json": bytesOf(JSON.stringify({ ...live, files: { "a.parquet": entryOf(a) } })), "data/a.parquet?v=run-1": 503 });
  await assert.rejects(downloadTables(ROOT, ["a"], refused.fetchFn), (e) => e instanceof DownloadError && /HTTP 503/.test(e.message));
  const offline = /** @type {typeof fetch} */ (async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(downloadTables(ROOT, ["a"], offline), DownloadError);
  const nothing = fakeFetch({ "site.json": bytesOf("{}") });
  await assert.rejects(downloadTables(ROOT, ["a"], nothing.fetchFn), /names no export/);
});

test("stale data and failed downloads read plainly", () => {
  assert.equal(describeError(new StaleDataError("x")).kind, "stale");
  assert.match(describeError(new StaleDataError("x")).text, /Reload the page/);
  assert.equal(describeError(new DownloadError("x")).kind, "download");
});
