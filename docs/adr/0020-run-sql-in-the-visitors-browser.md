# 20. Run the SQL console in the visitor's browser, from this site only

## Context

The site's SQL page lets a visitor query the same seven tables the other pages read. ADR 19 named
DuckDB-WASM for it. Checked on 2026-11-20, before building on it:

- `@duckdb/duckdb-wasm` 1.32.0 (DuckDB 1.4.3, MIT, published 2025-12-16) is the latest stable
  release; everything newer is a `-dev` prerelease, including the build npm tags `latest`.
- Its engine is 34.2 MB (about 7.6 MB gzip-compressed), its worker 0.8 MB.
- It ships with no Parquet reader: the first `read_parquet` downloads DuckDB's Parquet extension
  from `extensions.duckdb.org`. The site makes no third-party requests (ADR 17), and its
  Content-Security-Policy (`connect-src 'self'`) would block that download anyway.
- GitHub Pages cannot send response headers, so the policy is the `<meta>` tag SvelteKit writes
  into each page, set once for the whole site (`kit.csp`). A page given two policies obeys both,
  so a second tag can only tighten the first, never loosen it.

## Decision

- DuckDB runs in the visitor's browser, on the export's Parquet files as the site serves them:
  no server, no Snowflake, no credentials, no cost to anyone but the visitor's own download. It
  starts only when the visitor clicks, with the download's size on the button: an estimate made
  at build (each file gzip-compressed, as Pages sends it), checked against the live site after
  every deploy.
- Every file comes from this site. DuckDB's worker and engine are build assets (the worker is a
  file, not a `blob:` URL). The Parquet extension, DuckDB's own signed build for 1.4.3, is
  fetched when the site is built, checked against the size and sha256 pinned in
  `site/duckdb-extensions.json` (the build stops on any mismatch, and when the pinned DuckDB and
  the installed `@duckdb/duckdb-wasm` disagree), and served at `/duckdb/v1.4.3/wasm_eh/`;
  DuckDB's `custom_extension_repository` points there and its signature check stays on. Other
  extensions are not served: a query needing one gets a plain message.
- Each table is downloaded whole, in one request, when DuckDB starts, and handed to DuckDB as
  bytes (`registerFileBuffer`); tables are views over those files. Its address carries the
  export's run ID (`data/<table>.parquet?v=<run ID>`), so no cache can answer with a copy from
  an earlier export, and each file must have the size and sha256 that the live `site.json`
  (fetched past the browser's cache) lists, or nothing is queried and the page asks for a reload.
  Amended 2026-11-21: this replaced HTTP range requests (see below).
- After every deploy, `site.yml`'s `verify` job (`scripts/verify_live_site.py`, no credentials)
  fetches what the SQL page downloads from the live site, with a browser's headers, and checks
  every file against the deploy and the button's estimate against the bytes Pages sent.
- Only the SQL page's policy changes: after the build, `site/scripts/sql-csp.mjs` replaces that
  one page's `<meta>` policy with the site's plus `'wasm-unsafe-eval'` in `script-src` and
  `worker-src 'self'`. In Chromium DuckDB runs without them (it compiles WebAssembly inside the
  worker, which GitHub Pages serves with no policy), but browsers have differed on which policy
  governs a worker, so the page grants exactly what the engine needs. The browser tests check
  both directions: every other page's policy is the site's, the SQL page's differs by exactly
  those two additions. The SQL tests run in Chromium, Firefox and WebKit.
- A shared query travels in the address's fragment (`#sql=`), which never reaches a server or its
  logs, and fills the editor without running: a link someone sends starts no work on its own.
- Results show the first 1,000 rows and download as CSV up to 100,000, defused against
  spreadsheet formulas; the full count is always shown. Stop terminates DuckDB's worker, since
  DuckDB-WASM cannot reliably cancel a query, and the next run starts it again. Running out of
  memory, which phones reach far sooner than laptops, is an expected outcome with its own message.
- The table list beside the editor comes from the export contract, `_exports.yml`, through a
  derived and committed `site/src/lib/generated/exports.json` that a test keeps identical
  (`scripts/export_schema.py`). Every example query runs in the browser tests against the fixture
  export.

## Consequences

- A `<meta>` policy cannot express everything a header can (`frame-ancestors`, `sandbox`,
  reporting): an accepted limitation of GitHub Pages, for this page as for every other.
- A visitor who starts the console downloads about 14 MB, after a click and only on the SQL page:
  DuckDB's engine (34.2 MB, 7.7 MB as sent), its worker and extension (0.9 MB as sent) and the
  seven tables (5.1 MB as sent on 2026-11-21), all of it from the browser's cache on a return
  visit within the same export. Every table is downloaded even if a query reads one: simpler,
  and no query can meet a missing table.
- Upgrading DuckDB-WASM means updating `duckdb-extensions.json` in the same pull request (the
  build refuses a mismatch), after the two-week rule, with the new extension's size and sha256.

## Amendment, 2026-11-21: whole files, not byte ranges

What happened: about three minutes after the morning's deploy (Pages' `last-modified` 13:59:34
UTC), the SQL page failed in Chrome 154 at `export_restatements_largest`, whose file that deploy
had changed from 94,476 to 94,416 bytes: "Range request ... failed with error: NetworkError". An
hour later the same page worked, with no change to the code. Measured that day:

- In Chrome the range requests were answered uncompressed (`content-range: bytes 0-0/94416`, the
  real size, no `Content-Encoding`), so compression did not cause it.
- DuckDB reads a file over HTTP in several requests: a size probe, then the ranges that size
  implies. Pages and the browser each cache responses for up to ten minutes (`max-age=600`).
  Serving the probes from the previous version of a file and the reads from the new one
  reproduces the failure on the old page code (a local test in Chromium: "Range request ...
  failed with error", there from the server's 416). The exact inner error in Chrome cannot be
  recreated after the fact; the conditions and the failure match.
- Separately: Pages compresses every response, the Parquet files included
  (`application/octet-stream`), and when a request offers gzip and asks for a range, it answers
  with that range of the gzip copy (`content-range: bytes 0-99/84969` for a 94,416-byte file).
  Chromium asks for ranges with `Accept-Encoding: identity`; this site does not control what
  every browser sends.

Decision: read each table whole, in one request, at an address naming its export, and check it
against `site.json` before use (above). One request per file cannot be stitched from two
versions; the run ID keeps old copies out of caches; the sha256 check catches anything that still
gets through, with a plain message instead of a failed query or, worse, a query over a mix of
two exports; and how Pages answers ranges no longer matters. The cost: every table is downloaded
on Start (about 5 MB of the 14). The tests' server now compresses as Pages does, and the check
after each deploy covers what a local server cannot show.
