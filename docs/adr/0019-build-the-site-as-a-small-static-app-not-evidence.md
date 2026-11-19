# 19. Build the site as a small static app, not with Evidence

## Context

ADR 17 chose a static site rebuilt by the pipeline, and the Stage 9 plan named Evidence to build
it: pages as Markdown with SQL, compiled to static files, queried in the browser by DuckDB.
Checked on 2026-11-19, before building on it:

- The static Evidence framework (`@evidence-dev/evidence`) last released 40.1.8 on 2026-02-06.
  In August 2026 its makers open-sourced Evidence Core as its successor, described as connecting
  to a warehouse and building into Docker containers: a server, which this design rules out.
- Observable Framework, the plan's rejected alternative, last released 1.13.4 on 2026-03-02.
- The site's goals had also sharpened: as interactive as possible, a distinctive look (a trading
  terminal in two themes), keyboard navigation, and every page loading in under two seconds on
  a phone.

## Decision

- The site is a small SvelteKit app in `site/`, prerendered to static files for GitHub Pages
  (`@sveltejs/adapter-static`), under the base path `/Earnings-Watch`. Its dependencies are few,
  actively maintained and permissively licensed: Svelte and SvelteKit (MIT), hyparquet and
  hyparquet-compressors to read Parquet (MIT, no dependencies of their own), ECharts for charts
  when the pages need them (Apache-2.0), and DuckDB-WASM for the SQL console (MIT).
- The data logic stays in SQL. dbt's export models (`models/exports`) decide what each page
  shows; the app formats and filters it, nothing more.
- The numbers a visitor sees first are read from the export when the site is built, and are in
  the HTML itself: they never wait for JavaScript. Interactive pages read the same Parquet in the
  browser. DuckDB-WASM, several megabytes, loads only for the SQL console.
- Nothing loads from outside the site: fonts (IBM Plex, OFL) are self-hosted, and every page
  carries a Content-Security-Policy whose script hashes SvelteKit computes at build time.
- Dates are formatted in UTC everywhere: a quarter ending 2026-03-31 must not become March 30
  for a visitor in New York.
- The two-week rule (ADR 14) covers npm too: every package in `site/package-lock.json`,
  transitive ones included, must predate the lockfile's last change by 14 days
  (`scripts/check_npm_lock_age.py`); `npm ci` runs no install scripts; Dependabot proposes
  updates after a 14-day cooldown.
- The `site` check, required on `main`, builds the app against an invented fixture export
  generated from the export contract (`scripts/make_site_fixture.py`), then tests it in Chromium,
  served only under `/Earnings-Watch/` as Pages serves it: every page, no 404s, no console errors,
  no third-party requests, the answer present without JavaScript, the keyboard shortcuts (and
  their limits: never while typing, never with Ctrl, Cmd or Alt), the themes, UTC dates and
  reduced motion.

## Consequences

- More code than Evidence's Markdown pages, written and reviewed here; in exchange, full control
  of the interactions and the look, and no dependence on a framework whose static line has
  stopped.
- The risk the plan warned of, that a custom front end signals web development more than data
  engineering, is answered by where the logic lives: in dbt models with contracts and tests, and
  in an export contract the site is tested against.
- A wrong base path, the plan's first trap, fails a pull request, not the live site.
