import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { liveExport, tableFile } from "#lib/server/export.js";
import schema from "#lib/generated/exports.json" with { type: "json" };

/**
 * About how much a visitor downloads to start the console, measured when the site is built:
 * DuckDB's engine, its worker, its Parquet extension and every table, each gzip-compressed, as
 * GitHub Pages serves them (2026-11-21: the extension, 3,045,039 bytes, arrived as 714,849; Node's
 * gzip makes 708,117). The live site's check after each deploy (verify_live_site.py) compares
 * this with what Pages actually sent.
 * @param {string[]} tables
 */
function downloadBytes(tables) {
  const dist = path.resolve("node_modules/@duckdb/duckdb-wasm/dist");
  const pinned = JSON.parse(fs.readFileSync(path.resolve("duckdb-extensions.json"), "utf8"));
  const files = [
    path.join(dist, "duckdb-eh.wasm"),
    path.join(dist, "duckdb-browser-eh.worker.js"),
    ...pinned.extensions.map(
      (/** @type {{ name: string }} */ e) =>
        path.resolve("static/duckdb", pinned.duckdb, pinned.platform, `${e.name}.duckdb_extension.wasm`),
    ),
    ...tables.map(tableFile),
  ];
  return files.reduce((sum, file) => sum + zlib.gzipSync(fs.readFileSync(file)).length, 0);
}

export function load() {
  const files = liveExport().files ?? {};
  return {
    // Every exported table, its columns and their descriptions (from _exports.yml), with the
    // rows and bytes this export's file holds.
    tables: schema.tables.map((t) => ({
      ...t,
      rows: files[`${t.name}.parquet`]?.rows ?? null,
      bytes: files[`${t.name}.parquet`]?.bytes ?? null,
    })),
    downloadBytes: downloadBytes(schema.tables.map((t) => t.name)),
  };
}
