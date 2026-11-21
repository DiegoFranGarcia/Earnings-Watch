// DuckDB in the visitor's browser, started only when they ask for it (the SQL page imports this
// module on click). Everything comes from this site: DuckDB's worker and engine (served as files,
// so the page's policy needs no blob: workers), its Parquet extension (static/duckdb/, through
// custom_extension_repository) and the export's tables. Each table is downloaded whole, in one
// request, checked against the live site.json, and handed to DuckDB as bytes: DuckDB itself makes
// no request for data, so it can never read a file stitched from two exports (ADR 20).
import workerUrl from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";
import wasmUrl from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";
import { CSV_CAP, downloadTables, formatValue } from "#lib/sql.js";

/**
 * @typedef {{ name: string, type: string }} Column
 * @typedef {{ columns: Column[], rows: string[][], total: number, ms: number }} Result
 */

/**
 * Start DuckDB and make every exported table queryable by its name, as a view over its file.
 * @param {{ siteRoot: string, tables: string[] }} options siteRoot: the site's absolute URL, ending in "/"
 */
export async function start({ siteRoot, tables }) {
  const duckdb = await import("@duckdb/duckdb-wasm");
  const worker = new Worker(new URL(workerUrl, siteRoot));
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  try {
    // The tables and the engine download at the same time; nothing runs until both are here
    // and every table matched site.json.
    const [files] = await Promise.all([
      downloadTables(siteRoot, tables),
      db.instantiate(new URL(wasmUrl, siteRoot).href),
    ]);
    // Decimals as doubles, so results need no Arrow decimal handling to show or download.
    await db.open({ query: { castDecimalToDouble: true } });
    const conn = await db.connect();
    // Extensions from this site only; Parquet is loaded now, so a problem shows at start.
    await conn.query(`SET custom_extension_repository = '${new URL("duckdb", siteRoot).href}'`);
    await conn.query("LOAD parquet");
    for (const [table, bytes] of files) {
      await db.registerFileBuffer(`${table}.parquet`, bytes);
      await conn.query(`CREATE VIEW ${table} AS SELECT * FROM read_parquet('${table}.parquet')`);
    }
    return {
      /**
       * Run one query; keep up to CSV_CAP rows, formatted, and count them all.
       * @param {string} sql
       * @returns {Promise<Result>}
       */
      async run(sql) {
        const started = performance.now();
        const table = await conn.query(sql);
        const fields = table.schema.fields.map((f) => ({ name: f.name, type: String(f.type) }));
        const rows = [];
        const kept = Math.min(table.numRows, CSV_CAP);
        for (let i = 0; i < kept; i++) {
          const row = /** @type {any} */ (table.get(i));
          rows.push(fields.map((f) => formatValue(row?.[f.name], f.type)));
        }
        return { columns: fields, rows, total: table.numRows, ms: performance.now() - started };
      },
      /** Stop at once, whatever is running: DuckDB cannot reliably cancel a query, so the worker goes. */
      stop() {
        worker.terminate();
      },
    };
  } catch (error) {
    worker.terminate();
    throw error;
  }
}

/** @typedef {Awaited<ReturnType<typeof start>>} Console */
