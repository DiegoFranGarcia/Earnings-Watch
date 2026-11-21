// Serve the assembled site the way GitHub Pages serves a project site: only under the base
// path, a folder without its trailing slash redirected (301), index.html for a folder, 404
// elsewhere, and a single byte range answered with 206 (DuckDB reads Parquet in ranges). The
// browser tests run against this, so a wrong base path fails here as it would on Pages.
// SITE_DIR: the export with the app added beside it (build_site.py --add-app), as deployed.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const ROOT = path.resolve(process.env.SITE_DIR ?? "fixture");
const BASE = process.env.BASE_PATH ?? "/Earnings-Watch";
const PORT = Number(process.env.PORT ?? 4173);
/** @type {Record<string, string>} */
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".woff2": "font/woff2", ".svg": "image/svg+xml",
  ".parquet": "application/vnd.apache.parquet", ".png": "image/png", ".wasm": "application/wasm",
};

http
  .createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    const notFound = () => { res.writeHead(404, { "content-type": "text/plain" }); res.end("404"); };
    if (url.pathname !== BASE && !url.pathname.startsWith(`${BASE}/`)) return notFound();
    const rel = decodeURIComponent(url.pathname.slice(BASE.length)) || "/";
    const file = path.join(ROOT, rel);
    if (!file.startsWith(ROOT)) return notFound();
    let stat = fs.statSync(file, { throwIfNoEntry: false });
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
      if (!fs.existsSync(f)) return notFound();
      const size = fs.statSync(f).size;
      const headers = { "content-type": TYPES[path.extname(f)] ?? "application/octet-stream", "accept-ranges": "bytes" };
      const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? "");
      if (range && (range[1] || range[2])) {
        const start = range[1] ? Number(range[1]) : Math.max(0, size - Number(range[2]));
        const end = range[1] && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
        if (start > end || start >= size) {
          res.writeHead(416, { "content-range": `bytes */${size}` });
          return res.end();
        }
        res.writeHead(206, { ...headers, "content-range": `bytes ${start}-${end}/${size}`, "content-length": end - start + 1 });
        return req.method === "HEAD" ? res.end() : fs.createReadStream(f, { start, end }).pipe(res);
      }
      res.writeHead(200, { ...headers, "content-length": size });
      return req.method === "HEAD" ? res.end() : fs.createReadStream(f).pipe(res);
    }
  })
  .listen(PORT, () => console.log(`serving ${ROOT} at http://localhost:${PORT}${BASE}/`));
