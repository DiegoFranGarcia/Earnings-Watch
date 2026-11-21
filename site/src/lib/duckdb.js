// DuckDB in the visitor's browser, started only when they ask for it (the SQL page imports this
// module on click). Everything comes from this site: DuckDB's worker and engine (served as files,
// so the page's policy needs no blob: workers), its Parquet extension (static/duckdb/, through
// custom_extension_repository) and the export's Parquet files, read over HTTP range requests so
// a query fetches only the parts of a file it needs. Nothing reaches a third party.
import workerUrl from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";
import wasmUrl from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";
import { CSV_CAP, formatValue } from "#lib/sql.js";

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
    await db.instantiate(new URL(wasmUrl, siteRoot).href);
    await db.open({
      // Decimals as doubles, so results need no Arrow decimal handling to show or download.
      query: { castDecimalToDouble: true },
      // Read files in ranges (DuckDB-WASM 1.32 reads whole files unless told not to), probing
      // with a ranged GET: GitHub Pages answers ranged GETs with 206, but a ranged HEAD with 200.
      // A server without ranges still works, file by file in full.
      filesystem: { forceFullHTTPReads: false, allowFullHTTPReads: true, reliableHeadRequests: false },
    });
    const conn = await db.connect();
    // Extensions from this site only; Parquet is loaded now, so a problem shows at start.
    await conn.query(`SET custom_extension_repository = '${new URL("duckdb", siteRoot).href}'`);
    await conn.query("LOAD parquet");
    for (const table of tables) {
      await db.registerFileURL(`${table}.parquet`, new URL(`data/${table}.parquet`, siteRoot).href, duckdb.DuckDBDataProtocol.HTTP, false);
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
