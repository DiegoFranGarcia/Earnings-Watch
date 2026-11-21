<script>
  // Run SQL on the export, in the visitor's browser. The page itself (the tables, their columns,
  // the examples) is plain HTML; DuckDB loads only when the visitor starts it, and a query from a
  // shared link fills the editor but never runs until they click.
  import { onMount } from "svelte";
  import { replaceState } from "$app/navigation";
  import { count } from "#lib/format.js";
  import { link } from "#lib/pages.js";
  import { CSV_CAP, EXAMPLES, ROW_CAP, describeError, fromFragment, toCsv, toFragment } from "#lib/sql.js";

  let { data } = $props();

  let sql = $state(EXAMPLES[0].sql);
  let phase = $state(/** @type {"idle" | "starting" | "ready" | "running"} */ ("idle"));
  /** @type {import("#lib/duckdb.js").Console | null} */
  let duck = $state.raw(null);
  /** @type {import("#lib/duckdb.js").Result | null} */
  let result = $state.raw(null);
  /** @type {ReturnType<typeof describeError> | null} */
  let failure = $state.raw(null);
  let note = $state("");
  let copied = $state(false);

  // An estimate (gzip, measured at build): Pages decides the exact compression.
  const about = (/** @type {number} */ bytes) => `about ${Math.max(1, Math.round(bytes / 1e6))} MB`;
  const busy = $derived(phase === "starting" || phase === "running");

  onMount(() => {
    const shared = fromFragment(location.hash);
    if (shared) {
      sql = shared;
      note = "This query came from a link. Read it, then run it if you want to.";
    }
  });

  function remember() {
    replaceState(`${location.pathname}${location.search}${toFragment(sql)}`, {});
  }

  async function run() {
    if (busy || !sql.trim()) return;
    failure = null;
    note = "";
    remember();
    try {
      if (!duck) {
        phase = "starting";
        const { start } = await import("#lib/duckdb.js");
        duck = await start({ siteRoot: new URL(link("/"), location.origin).href, tables: data.tables.map((t) => t.name) });
      }
      phase = "running";
      result = await duck.run(sql);
      phase = "ready";
    } catch (error) {
      result = null;
      failure = describeError(error);
      phase = duck ? "ready" : "idle";
    }
  }

  function stop() {
    duck?.stop();
    duck = null;
    phase = "idle";
    note = "Stopped. DuckDB starts again on the next run (from your browser's cache).";
  }

  /** @param {KeyboardEvent} e */
  function keys(e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      run();
    }
  }

  /** @param {string} text */
  function pick(text) {
    sql = text;
    failure = null;
    note = "";
    remember();
  }

  async function share() {
    remember();
    try {
      await navigator.clipboard.writeText(location.href);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      note = "The link is in your address bar: copy it from there.";
    }
  }

  function download() {
    if (!result) return;
    const csv = toCsv(result.columns.map((c) => c.name), result.rows);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "earningswatch-query.csv" });
    a.click();
    URL.revokeObjectURL(url);
  }
</script>

<svelte:head>
  <title>SQL: EarningsWatch</title>
  <meta name="description" content="Run SQL on EarningsWatch's tables in your browser, with DuckDB: the same files the site's pages read." />
</svelte:head>

<main>
  <section class="hero">
    <h1>Ask the data yourself</h1>
    <p class="prose lede">
      SQL on the same seven tables these pages read, run by DuckDB inside your browser. Nothing you
      type leaves your computer, and nothing here costs anyone anything: there is no server, only
      files.
    </p>
  </section>

  <div class="layout">
    <section class="work" aria-label="Query">
      <ul class="examples" aria-label="Example queries">
        {#each EXAMPLES as ex (ex.id)}
          <li><button type="button" class="example" data-example={ex.id} title={ex.about} onclick={() => pick(ex.sql)}>{ex.title}</button></li>
        {/each}
      </ul>

      <label class="visually-hidden" for="sql">SQL query</label>
      <textarea
        id="sql"
        bind:value={sql}
        onkeydown={keys}
        rows="12"
        spellcheck="false"
        autocapitalize="off"
        autocomplete="off"
        {...{ autocorrect: "off" }}
        data-testid="editor"
      ></textarea>

      <div class="actions">
        <button type="button" class="primary" onclick={run} disabled={busy} data-testid="run">
          {#if phase === "starting"}Starting DuckDB…{:else if phase === "running"}Running…{:else if duck}Run <span class="key">Ctrl+Enter</span>{:else}Start DuckDB and run <span class="key">downloads {about(data.downloadBytes)}</span>{/if}
        </button>
        {#if busy}<button type="button" onclick={stop} data-testid="stop">Stop</button>{/if}
        <button type="button" onclick={share}>{copied ? "Link copied" : "Copy link to this query"}</button>
        {#if result && result.total > 0}<button type="button" onclick={download} data-testid="csv">Download CSV</button>{/if}
      </div>

      {#if note}<p class="note muted" data-testid="note">{note}</p>{/if}

      {#if failure}
        <div class="failure" role="alert" data-testid="error" data-kind={failure.kind}>
          <p>{failure.text}</p>
          {#if failure.detail !== failure.text}<details><summary>DuckDB's message</summary><pre>{failure.detail}</pre></details>{/if}
        </div>
      {/if}

      <div aria-live="polite">
        {#if result}
          <p class="status muted" data-testid="status">
            {count(result.total)} {result.total === 1 ? "row" : "rows"} in {count(Math.round(result.ms))} ms{#if result.total > ROW_CAP}: showing the first {count(ROW_CAP)}{/if}{#if result.total > CSV_CAP}; the CSV holds the first {count(CSV_CAP)}{/if}.
          </p>
          {#if result.columns.length}
            <div class="tablewrap">
              <table data-testid="result">
                <thead>
                  <tr>{#each result.columns as c, i (i)}<th scope="col" title={c.type}>{c.name}</th>{/each}</tr>
                </thead>
                <tbody>
                  {#each result.rows.slice(0, ROW_CAP) as row, r (r)}
                    <tr>{#each row as cell, i (i)}<td>{cell}</td>{/each}</tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        {/if}
      </div>
    </section>

    <aside class="tables" aria-label="Tables">
      <h2>Tables</h2>
      {#each data.tables as t (t.name)}
        <details data-table={t.name}>
          <summary><code>{t.name}</code>{#if t.rows != null}<span class="rows muted">{count(t.rows)} rows</span>{/if}</summary>
          {#if t.description}<p class="about">{t.description}</p>{/if}
          <ul class="columns">
            {#each t.columns as c (c.name)}
              <li><code>{c.name}</code> <span class="muted">{c.type}</span>{#if c.description}<span class="desc">{c.description}</span>{/if}</li>
            {/each}
          </ul>
        </details>
      {/each}
      <p class="muted small">
        DuckDB's SQL, with its Parquet support. Results show the first {count(ROW_CAP)} rows; a CSV
        holds up to {count(CSV_CAP)}. Stop ends a query at once.
      </p>
    </aside>
  </div>
</main>

<style>
  .hero { padding: 48px 0 16px; }
  h1 { font-size: clamp(28px, 4.6vw, 50px); line-height: 1.08; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 14px; }
  .lede { max-width: 68ch; color: var(--muted); font-size: 15.5px; margin: 0; }
  .layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 28px; align-items: start; }
  .examples { list-style: none; padding: 0; margin: 0 0 10px; display: flex; flex-wrap: wrap; gap: 6px; }
  .example { font: inherit; font-size: 12.5px; background: var(--panel); color: var(--text); border: 1px solid var(--rule); padding: 4px 10px; cursor: pointer; }
  .example:hover { border-color: var(--accent); color: var(--accent); }
  textarea {
    width: 100%; box-sizing: border-box; font-family: "IBM Plex Mono", monospace; font-size: 13.5px; line-height: 1.5;
    color: var(--text); background: var(--panel); border: 1px solid var(--rule); padding: 10px 12px; resize: vertical; tab-size: 2;
  }
  textarea:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
  .actions button { font: inherit; font-size: 13px; background: none; color: var(--text); border: 1px solid var(--rule); padding: 6px 12px; cursor: pointer; }
  .actions .primary { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
  .actions button:disabled { opacity: 0.6; cursor: progress; }
  .key { opacity: 0.75; font-size: 11.5px; margin-left: 6px; }
  .note { font-size: 13px; margin: 4px 0 8px; }
  .failure { border-left: 3px solid var(--accent); background: var(--panel); padding: 8px 12px; margin: 8px 0; font-size: 13.5px; }
  .failure p { margin: 0 0 4px; }
  .failure pre { white-space: pre-wrap; font-size: 12px; margin: 6px 0 0; }
  .status { font-size: 13px; margin: 8px 0; }
  .tablewrap { border: 1px solid var(--rule); overflow: auto; max-height: 560px; }
  table { border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; width: max-content; min-width: 100%; }
  th { position: sticky; top: 0; background: var(--panel); color: var(--muted); font-weight: 500; text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--rule); }
  td { padding: 3px 10px; white-space: nowrap; max-width: 40ch; overflow: hidden; text-overflow: ellipsis; }
  tbody tr:nth-child(odd) { background: var(--band); }
  .tables h2 { font-size: 15px; font-weight: 600; margin: 0 0 8px; }
  .tables details { border-top: 1px solid var(--rule); padding: 6px 0; }
  .tables summary { cursor: pointer; font-size: 13px; }
  .tables code { font-size: 12.5px; }
  .rows { margin-left: 8px; font-size: 12px; }
  .about { font-size: 12.5px; color: var(--muted); margin: 6px 0; }
  .columns { list-style: none; padding: 0; margin: 4px 0 6px; font-size: 12px; }
  .columns li { padding: 2px 0; }
  .desc { display: block; color: var(--muted); font-size: 11.5px; margin-left: 2px; }
  .small { font-size: 12px; margin-top: 12px; }
  @media (max-width: 860px) {
    .layout { grid-template-columns: minmax(0, 1fr); }
  }
</style>
