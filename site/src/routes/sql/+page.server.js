import fs from "node:fs";
import path from "node:path";
import { liveExport } from "#lib/server/export.js";
import schema from "#lib/generated/exports.json" with { type: "json" };

/** The files a visitor downloads to start the console, measured when the site is built. */
function downloadBytes() {
  const dist = path.resolve("node_modules/@duckdb/duckdb-wasm/dist");
  const engine = ["duckdb-eh.wasm", "duckdb-browser-eh.worker.js"].map((f) => fs.statSync(path.join(dist, f)).size);
  const pinned = JSON.parse(fs.readFileSync(path.resolve("duckdb-extensions.json"), "utf8"));
  return [...engine, ...pinned.extensions.map((/** @type {{ bytes: number }} */ e) => e.bytes)].reduce((a, b) => a + b, 0);
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
    downloadBytes: downloadBytes(),
  };
}
