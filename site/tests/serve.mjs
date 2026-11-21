// Serve the assembled site the way GitHub Pages serves a project site, so the browser tests meet
// what visitors meet: only under the base path, a folder without its trailing slash redirected
// (301), index.html for a folder, 404 elsewhere, the query string ignored, and, as measured on
// the live site on 2026-11-21, every response gzip-compressed when the request offers gzip (as
// browsers do for whole files), with a byte range answered from the compressed copy: `Range: bytes=0-99`
// with gzip offered gets bytes 0-99 of the gzip stream, `content-range: bytes 0-99/<gzip size>`.
// (Chromium asks for ranges uncompressed; the SQL page downloads whole files anyway, ADR 20.)
// SITE_DIR: the export with the app added beside it (build_site.py --add-app), as deployed.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import zlib from "node:zlib";

const ROOT = path.resolve(process.env.SITE_DIR ?? "fixture");
const BASE = process.env.BASE_PATH ?? "/Earnings-Watch";
const PORT = Number(process.env.PORT ?? 4173);
/** @type {Record<string, string>} */
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".woff2": "font/woff2", ".svg": "image/svg+xml",
  ".png": "image/png", ".wasm": "application/wasm",
  // Pages has no type for Parquet: application/octet-stream, like any unknown extension.
};

/** Each file's gzip copy, made once per file version. @type {Map<string, Buffer>} */
const gzipped = new Map();

/** @param {string} file @param {fs.Stats} stat */
function gzipOf(file, stat) {
  const key = `${file}:${stat.mtimeMs}:${stat.size}`;
  if (!gzipped.has(key)) gzipped.set(key, zlib.gzipSync(fs.readFileSync(file)));
  return /** @type {Buffer} */ (gzipped.get(key));
}

http
  .createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    const notFound = () => { res.writeHead(404, { "content-type": "text/plain" }); res.end("404"); };
    if (url.pathname !== BASE && !url.pathname.startsWith(`${BASE}/`)) return notFound();
    const rel = decodeURIComponent(url.pathname.slice(BASE.length)) || "/";
    const file = path.join(ROOT, rel);
    if (!file.startsWith(ROOT)) return notFound();
    const stat = fs.statSync(file, { throwIfNoEntry: false });
    if (stat?.isDirectory()) {
      if (!url.pathname.endsWith("/")) {
        res.writeHead(301, { location: `${url.pathname}/${url.search}` });
        return res.end();
      }
      return send(path.join(file, "index.html"));
    }
    return stat?.isFile() ? send(file) : notFound();

    /** @param {string} f */
    function send(f) {
      const fileStat = fs.statSync(f, { throwIfNoEntry: false });
      if (!fileStat?.isFile()) return notFound();
      const gzip = /\bgzip\b/.test(String(req.headers["accept-encoding"] ?? ""));
      const body = gzip ? gzipOf(f, fileStat) : fs.readFileSync(f);
      /** @type {Record<string, string | number>} */
      const headers = {
        "content-type": TYPES[path.extname(f)] ?? "application/octet-stream",
        "accept-ranges": "bytes",
        vary: "Accept-Encoding",
        ...(gzip ? { "content-encoding": "gzip" } : {}),
      };
      const size = body.length;
      const range = /^bytes=(\d*)-(\d*)$/.exec(String(req.headers.range ?? ""));
      if (range && (range[1] || range[2])) {
        const start = range[1] ? Number(range[1]) : Math.max(0, size - Number(range[2]));
        const end = range[1] && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
        if (start > end || start >= size) {
          res.writeHead(416, { "content-range": `bytes */${size}` });
          return res.end();
        }
        res.writeHead(206, { ...headers, "content-range": `bytes ${start}-${end}/${size}`, "content-length": end - start + 1 });
        return res.end(req.method === "HEAD" ? undefined : body.subarray(start, end + 1));
      }
      res.writeHead(200, { ...headers, "content-length": size });
      return res.end(req.method === "HEAD" ? undefined : body);
    }
  })
  .listen(PORT, () => console.log(`serving ${ROOT} at http://localhost:${PORT}${BASE}/`));
