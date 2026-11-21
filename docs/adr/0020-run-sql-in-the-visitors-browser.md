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
  starts only when the visitor clicks, with the download's size on the button.
- Every file comes from this site. DuckDB's worker and engine are build assets (the worker is a
  file, not a `blob:` URL). The Parquet extension, DuckDB's own signed build for 1.4.3, is
  fetched when the site is built, checked against the size and sha256 pinned in
  `site/duckdb-extensions.json` (the build stops on any mismatch, and when the pinned DuckDB and
  the installed `@duckdb/duckdb-wasm` disagree), and served at `/duckdb/v1.4.3/wasm_eh/`;
  DuckDB's `custom_extension_repository` points there and its signature check stays on. Other
  extensions are not served: a query needing one gets a plain message.
- Tables are views over the files, read with HTTP range requests, so a query fetches only what
  it needs (GitHub Pages and the tests' server both answer ranges).
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
- The site grows by about 38 MB of files a visitor downloads only on the SQL page, after a click.
- Upgrading DuckDB-WASM means updating `duckdb-extensions.json` in the same pull request (the
  build refuses a mismatch), after the two-week rule, with the new extension's size and sha256.
