// Serve the assembled site the way GitHub Pages serves a project site: only under the base
// path, a folder without its trailing slash redirected (301), index.html for a folder, 404
// elsewhere. The browser tests run against this, so a wrong base path fails here as it would on
// Pages. SITE_DIR: the export with the app added beside it (build_site.py --add-app), as deployed.
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
  ".parquet": "application/vnd.apache.parquet", ".png": "image/png",
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
      res.writeHead(200, { "content-type": TYPES[path.extname(f)] ?? "application/octet-stream" });
      fs.createReadStream(f).pipe(res);
    }
  })
  .listen(PORT, () => console.log(`serving ${ROOT} at http://localhost:${PORT}${BASE}/`));
