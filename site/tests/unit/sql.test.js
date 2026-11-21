// The SQL page's logic and its policy change, on their own: node --test, no browser.
import assert from "node:assert/strict";
import { test } from "node:test";
import { allowWasm } from "../../scripts/sql-csp.mjs";
import { EXAMPLES, describeError, formatValue, fromFragment, toCsv, toFragment } from "#lib/sql.js";

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
