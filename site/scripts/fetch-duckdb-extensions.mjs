// Put the DuckDB extensions the SQL page needs into static/duckdb/, where the site serves them
// (DuckDB's custom_extension_repository points there), so the page never fetches from
// extensions.duckdb.org. Runs before every build (npm run build). Each file is checked against
// the size and sha256 pinned in duckdb-extensions.json: a file already there that matches is
// kept, anything else is downloaded again, and a download that does not match stops the build.
// The extensions are DuckDB's own signed builds; DuckDB checks the signature when it loads one.
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const SITE = path.resolve(import.meta.dirname, "..");
const config = JSON.parse(fs.readFileSync(path.join(SITE, "duckdb-extensions.json"), "utf8"));
const installed = JSON.parse(
  fs.readFileSync(path.join(SITE, "node_modules/@duckdb/duckdb-wasm/package.json"), "utf8"),
).version;

if (installed !== config.duckdb_wasm) {
  throw new Error(
    `@duckdb/duckdb-wasm is ${installed}, but duckdb-extensions.json pins extensions for ` +
      `${config.duckdb_wasm} (DuckDB ${config.duckdb}): update both together`,
  );
}

/** @param {Buffer} data */
const sha256 = (data) => createHash("sha256").update(data).digest("hex");

for (const ext of config.extensions) {
  const file = path.join(SITE, "static/duckdb", config.duckdb, config.platform, `${ext.name}.duckdb_extension.wasm`);
  /** @param {Buffer} data */
  const matches = (data) => data.length === ext.bytes && sha256(data) === ext.sha256;
  if (fs.existsSync(file) && matches(fs.readFileSync(file))) {
    console.log(`${ext.name}: already in place (${ext.bytes.toLocaleString("en-US")} bytes, sha256 matches)`);
    continue;
  }
  const response = await fetch(ext.url);
  if (!response.ok) throw new Error(`${ext.name}: ${ext.url} answered HTTP ${response.status}`);
  const data = Buffer.from(await response.arrayBuffer());
  if (!matches(data)) {
    throw new Error(
      `${ext.name}: ${ext.url} gave ${data.length} bytes with sha256 ${sha256(data)}, ` +
        `not the pinned ${ext.bytes} bytes and ${ext.sha256}`,
    );
  }
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, data);
  console.log(`${ext.name}: downloaded and verified (${ext.bytes.toLocaleString("en-US")} bytes)`);
}
