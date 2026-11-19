// Read one exported table, at build time or in the browser. The export writes ZSTD Parquet
// (site_export.py), so ZSTD is the one codec the site decodes, with fzstd: plain JavaScript, no
// WebAssembly, which the Content-Security-Policy would block in the browser.
import { decompress } from "fzstd";
import { parquetReadObjects } from "hyparquet";

const compressors = { ZSTD: (/** @type {Uint8Array} */ input) => decompress(input) };

/**
 * Every row of a Parquet file, with 64-bit integers as plain numbers.
 * @param {ArrayBuffer | import("hyparquet").AsyncBuffer} file
 * @returns {Promise<Record<string, any>[]>}
 */
export async function readParquet(file) {
  const rows = await parquetReadObjects({ file, compressors });
  return rows.map((row) =>
    Object.fromEntries(Object.entries(row).map(([k, v]) => [k, typeof v === "bigint" ? Number(v) : v])),
  );
}
