<script>
  // Do companies file their 10-Ks and 10-Qs on time? Everything is in the HTML, chart included;
  // in the browser, the form toggle redraws it and keeps the choice in the page's address.
  import { onMount } from "svelte";
  import { replaceState } from "$app/navigation";
  import { count, percent } from "#lib/format.js";
  import TimelinessChart from "#lib/components/TimelinessChart.svelte";
  import { DEFAULT, FIRST_YEAR, FORMS, GROUPS, PHASE_IN, parseState, series, share, splitYear, toSearch, yearOf } from "#lib/timeliness.js";

  let { data } = $props();

  /** @type {import("#lib/timeliness.js").State} */
  let s = $state({ ...DEFAULT });
  let ready = $state(false);

  onMount(() => {
    s = parseState(new URL(location.href).searchParams);
    ready = true;
  });

  $effect(() => {
    const search = toSearch(s);
    if (ready) replaceState(`${location.pathname}${search}`, {});
  });

  /** @param {import("#lib/timeliness.js").Cell[]} cells @param {string} group */
  const find = (cells, group) => cells.find((c) => c.group === group);
  /** @param {number | null} v */
  const days = (v) => (v == null ? "—" : `${Number.isInteger(v) ? v : v.toFixed(1)} days`);
  /** @param {number} year */
  const toDate = (year) => (year > data.complete ? " (to date)" : "");

  // The opening: 10-Ks for the last complete year, the largest companies against the smallest.
  const opening = $derived(yearOf(data.cells, "10-K", data.complete));
  const large = $derived(find(opening, "large_accelerated"));
  const middle = $derived(find(opening, "accelerated"));
  const small = $derived(find(opening, "non_accelerated"));

  const lines = $derived(series(data.cells, s.form));
  const split = $derived(splitYear(data.cells, s.form, data.complete));
  const splitCells = $derived(split == null ? [] : yearOf(data.cells, s.form, split));
  const timing = $derived(yearOf(data.cells, s.form, data.complete));
  const years = $derived(
    [...new Set(data.cells.filter((c) => c.form === s.form && c.year >= FIRST_YEAR).map((c) => c.year))]
      .sort((a, b) => b - a)
      .map((year) => ({ year, cells: yearOf(data.cells, s.form, year) })),
  );
  /** An export from before this page: no deadlines or group medians until the next one. */
  const awaiting = $derived(data.cells.some((c) => c.deadline == null));
</script>

<svelte:head>
  <title>Filing timeliness: EarningsWatch</title>
  <meta name="description" content="How many 10-K and 10-Q filings arrive by the deadline, within an extension, or late, by filer size and year, from SEC filings." />
</svelte:head>

<main>
  <section class="hero">
    <h1>Do companies file their reports on time?</h1>
    <div class="answer">
      <div class="fig">
        <span class="n" data-testid="large">{large ? percent(share(large), 0) : "—"}</span>
        <span class="who">Large accelerated filers</span>
      </div>
      <div class="fig">
        <span class="n lead" data-testid="small">{small ? percent(share(small), 0) : "—"}</span>
        <span class="who">Non-accelerated filers</span>
      </div>
    </div>
    <div class="ctx prose">
      <p class="of">of 10-Ks for periods ending in {data.complete} were filed by the deadline.</p>
      <p class="def" data-testid="deadlines">
        {#if large?.deadline != null && small?.deadline != null}
          Each group against its own deadline: smaller companies get more time, {small.deadline}
          days after the year ends to the largest companies' {large.deadline}, and still miss it
          more often.
        {:else}
          Each group against its own deadline: smaller companies get more time, and still miss it
          more often.
        {/if}
        {#if middle}Accelerated filers{#if middle.deadline != null}, due in {middle.deadline} days{/if}: {percent(share(middle), 0)}.{/if}
      </p>
    </div>
  </section>

  <section class="groups prose">
    <p>
      Filer groups follow the SEC's filer status, set mostly by public float: <b>large accelerated</b>
      filers have $700m or more, <b>accelerated</b> filers $75m to $700m, and the rest are
      <b>non-accelerated</b>, as are, since 2020, most companies with under $100m in annual revenue.
    </p>
  </section>

  <section class="controls" aria-label="Choices">
    <div class="toggle" role="group" aria-label="Which form">
      {#each FORMS as form (form)}
        <button type="button" aria-pressed={s.form === form} onclick={() => (s.form = form)}>
          {form} ({form === "10-K" ? "annual" : "quarterly"})
        </button>
      {/each}
    </div>
  </section>

  <section>
    <h2>{s.form}s filed by the deadline, each year</h2>
    <TimelinessChart {lines} complete={data.complete} form={s.form} />
    <p class="note prose muted">
      Shaded: {PHASE_IN[0]} to {PHASE_IN[1]}, when companies phased into XBRL tagging, which these
      figures come from; and {data.complete + 1}, whose filings are not all due yet. A deadline on
      a weekend, a federal holiday or another day EDGAR was closed moves to the next business day,
      as the SEC's rules allow.
    </p>
    <details>
      <summary>The figures, year by year</summary>
      <div class="tablewrap">
        <table data-testid="years">
          <thead>
            <tr>
              <th scope="col">Period year</th>
              {#each GROUPS as [group, label] (group)}<th scope="col">{label}</th>{/each}
            </tr>
          </thead>
          <tbody>
            {#each years as y (y.year)}
              <tr>
                <td>{y.year}{toDate(y.year)}</td>
                {#each GROUPS as [group] (group)}
                  {@const c = find(y.cells, group)}
                  <td>{c ? percent(share(c)) : "—"} <span class="muted">{c ? `of ${count(c.filings)}` : ""}</span></td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </details>
  </section>

  <section>
    <h2>By the deadline, within an extension, or late</h2>
    <p class="prose muted lede">
      A company that expects to miss a deadline can file a notice (Form 12b-25: NT 10-K or NT
      10-Q). A report filed within 15 days after the deadline, 5 for a 10-Q, then counts as filed
      on time under the SEC's rules. We have the notices only from 2025, so this split starts
      there; before it, the chart counts filings that used an extension as not on time.
    </p>
    {#if split == null}
      <p class="prose muted">No year with late-filing notices yet.</p>
    {:else}
      <h3 data-testid="split-year">{s.form}s for periods ending in {split}{toDate(split)}</h3>
      <ul class="split" data-testid="split">
        {#each splitCells as c (c.group)}
          {@const parts = [c.onTime / c.filings, c.within / c.filings, c.late / c.filings]}
          <li>
            <span class="who">{GROUPS.find(([g]) => g === c.group)?.[1]}</span>
            <span class="bar" aria-hidden="true">
              <i class="on" style:width="{parts[0] * 100}%"></i><i class="ext" style:width="{parts[1] * 100}%"></i><i class="late" style:width="{parts[2] * 100}%"></i>
            </span>
            <span class="nums">
              {percent(parts[0])} by the deadline, {percent(parts[1])} within an extension,
              {percent(parts[2])} late. {count(c.notices)} notices, of {count(c.filings)} filings.
            </span>
          </li>
        {/each}
      </ul>
      <p class="key muted" aria-hidden="true"><span><i class="on"></i>By the deadline</span><span><i class="ext"></i>Within an extension</span><span><i class="late"></i>Late</span></p>
    {/if}
  </section>

  <section>
    <h2>How long filers take: {s.form}s for periods ending in {data.complete}</h2>
    {#if awaiting}
      <p class="prose muted" data-testid="awaiting">Deadlines and each group's medians arrive with the next data export.</p>
    {/if}
    <div class="tablewrap">
      <table data-testid="timing">
        <thead>
          <tr>
            <th scope="col">Filer group</th>
            <th scope="col">Deadline</th>
            <th scope="col">Median</th>
            <th scope="col">90th percentile</th>
            <th scope="col">Past the deadline, when not on time</th>
            <th scope="col">Filings</th>
          </tr>
        </thead>
        <tbody>
          {#each timing as c (c.group)}
            <tr>
              <td data-label="Filer group">{GROUPS.find(([g]) => g === c.group)?.[1]}</td>
              <td data-label="Deadline">{c.deadline == null ? "—" : `${c.deadline} days${c.extension == null ? "" : `, +${c.extension} with a notice`}`}</td>
              <td data-label="Median">{days(c.median)}</td>
              <td data-label="90th percentile">{days(c.p90)}</td>
              <td data-label="Past the deadline, when not on time">{c.lateBy == null ? "—" : `${days(c.lateBy)} (median)`}</td>
              <td data-label="Filings">{count(c.filings)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="note prose muted">Days after the period ends. Half the filings came in by the median, nine in ten by the 90th percentile.</p>
  </section>

  <p class="foot muted prose">
    Original 10-Ks and 10-Qs from the SEC's Financial Statement Data Sets, with each filer's
    status as recorded on the filing; late-filing notices from EDGAR's daily index. Amendments
    are not measured. The days EDGAR was closed are federal holidays and the closures the SEC
    announced, each with its source in the pipeline's seed data.
  </p>
</main>

<style>
  .hero { padding: 48px 0 24px; border-bottom: 1px solid var(--rule); }
  h1 { font-size: clamp(28px, 4.6vw, 50px); line-height: 1.08; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 24px; max-width: 22ch; }
  .answer { display: flex; flex-wrap: wrap; gap: 8px 40px; align-items: flex-end; margin: 0 0 12px; }
  .fig { display: flex; flex-direction: column; }
  .n { font-size: clamp(44px, 8vw, 92px); line-height: 0.95; font-weight: 500; font-variant-numeric: tabular-nums; color: var(--text); }
  .n.lead { color: var(--accent); }
  .who { font-size: 13px; color: var(--muted); }
  .ctx p { margin: 0; max-width: 60ch; }
  .of { font-size: 20px; line-height: 1.3; margin-bottom: 8px !important; }
  .def { font-size: 15.5px; color: var(--muted); }
  .groups { padding: 18px 0 4px; max-width: 80ch; font-size: 14.5px; color: var(--muted); }
  .groups b { color: var(--text); font-weight: 500; }
  h2 { font-size: 17px; font-weight: 600; margin: 28px 0 10px; }
  h3 { font-size: 14px; font-weight: 600; margin: 14px 0 8px; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin: 14px 0 4px; }
  .toggle { display: inline-flex; border: 1px solid var(--rule); flex-wrap: wrap; }
  .toggle button { font: inherit; font-size: 13px; background: none; color: var(--muted); border: 0; padding: 5px 12px; cursor: pointer; }
  .toggle button[aria-pressed="true"] { background: var(--accent); color: var(--on-accent); }
  .note { font-size: 12.5px; max-width: 80ch; margin: 6px 0; }
  .lede { max-width: 80ch; margin: 0 0 4px; font-size: 13.5px; }
  details { margin: 8px 0; }
  summary { cursor: pointer; font-size: 13.5px; color: var(--accent); }
  .tablewrap { border: 1px solid var(--rule); overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
  th { background: var(--panel); color: var(--muted); font-weight: 500; text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--rule); }
  td { text-align: right; padding: 4px 8px; white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  tbody tr:nth-child(odd) { background: var(--band); }
  .split { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; max-width: 880px; }
  .split li { display: grid; grid-template-columns: 18ch 1fr; gap: 4px 14px; align-items: center; font-size: 13px; }
  .split .who { font-size: 13px; color: var(--text); }
  .bar { display: flex; height: 14px; border: 1px solid var(--rule); background: var(--panel); }
  .bar i { display: block; height: 100%; }
  .on { background: var(--rule); }
  .ext { background: var(--accent-dim); }
  .late { background: var(--accent); }
  .nums { grid-column: 2; color: var(--muted); font-size: 12.5px; }
  .key { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 12px; margin: 10px 0 0; }
  .key i { display: inline-block; width: 12px; height: 10px; margin-right: 6px; vertical-align: -1px; }
  .foot { font-size: 12.5px; margin: 28px 0 40px; max-width: 80ch; }
  @media (max-width: 760px) {
    .split li { grid-template-columns: 1fr; }
    .nums { grid-column: 1; }
    [data-testid="timing"] thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
    [data-testid="timing"], [data-testid="timing"] tbody, [data-testid="timing"] tr, [data-testid="timing"] td { display: block; }
    [data-testid="timing"] tbody tr { border: 1px solid var(--rule); margin: 0 0 8px; padding: 8px 10px; background: var(--panel) !important; }
    [data-testid="timing"] td { display: flex; justify-content: space-between; gap: 12px; padding: 2px 0; text-align: right !important; white-space: normal; }
    [data-testid="timing"] td::before { content: attr(data-label); color: var(--muted); text-align: left; }
    [data-testid="timing"] td:first-child { display: block; text-align: left !important; font-size: 14px; font-weight: 500; }
    [data-testid="timing"] td:first-child::before { content: none; }
    .tablewrap:has([data-testid="timing"]) { border: 0; }
  }
</style>
