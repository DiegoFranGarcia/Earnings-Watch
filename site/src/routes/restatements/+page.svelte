<script>
  // How often companies change numbers they already reported, and how. The opening and the
  // years are in the HTML; the browser loads the largest restatements from the export's Parquet
  // and filters them there, keeping the choices in the page's address.
  import { onMount } from "svelte";
  import { replaceState } from "$app/navigation";
  import { count, money, moneyChange, percent } from "#lib/format.js";
  import { link } from "#lib/pages.js";
  import { readParquet } from "#lib/parquet.js";
  import RestatementsChart from "#lib/components/RestatementsChart.svelte";
  import {
    DEFAULT,
    KINDS,
    KIND_LABELS,
    METRICS,
    METRIC_LABELS,
    ORDERS,
    PHASE_IN,
    awaitingFigures,
    barValue,
    filterRestatements,
    headline,
    parseState,
    sortRestatements,
    toRestatement,
    toSearch,
    yearly,
  } from "#lib/restatements.js";

  let { data } = $props();

  /** @type {import("#lib/restatements.js").Restatement[] | null} */
  let rows = $state.raw(null);
  let failed = $state(false);
  /** @type {import("#lib/restatements.js").State} */
  let s = $state({ ...DEFAULT });
  let ready = $state(false);

  const screened = $derived(new Set(data.screened));
  const years = $derived(yearly(data.byYear, s.metric));
  const opening = $derived(headline(yearly(data.byYear, "net_income"), data.fullYear));
  const figure = $derived(METRIC_LABELS[s.metric].toLowerCase());
  const matching = $derived(rows ? sortRestatements(filterRestatements(rows, s), s.order) : data.first);
  const kinds = $derived(KINDS.filter(([kind]) => s.tags || kind !== "tag_switch"));
  const changed = $derived(toSearch(s) !== "");
  const awaiting = $derived(awaitingFigures(data.byYear));

  onMount(() => {
    s = parseState(new URL(location.href).searchParams);
    ready = true;
    (async () => {
      try {
        const response = await fetch(`${link("/")}data/export_restatements_largest.parquet`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        rows = (await readParquet(await response.arrayBuffer())).map(toRestatement);
      } catch {
        failed = true;
      }
    })();
  });

  $effect(() => {
    const search = toSearch(s);
    if (ready) replaceState(`${location.pathname}${search}`, {});
  });

  /** @param {number} cik */
  const companyLink = (cik) =>
    screened.has(cik)
      ? `${link("/company")}${cik}/`
      : `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${cik}&type=10-&dateb=&owner=include&count=40`;
</script>

<svelte:head>
  <title>Restatements: EarningsWatch</title>
  <meta name="description" content="How often US public companies change figures they already reported, and how: amendments, later filings and tag switches, from SEC filings." />
</svelte:head>

<main>
  <section class="hero">
    <h1>How often do companies change numbers they already reported?</h1>
    <div class="answer">
      <div class="n" data-testid="share">{opening.share == null ? "—" : percent(opening.share, 0)}</div>
      <div class="ctx prose">
        <p class="of">
          of the net income figures companies changed in {opening.year} came in an amendment
          (a filing marked /A). The other {opening.share == null ? "—" : percent(1 - opening.share, 0)} changed
          in a later filing.
        </p>
        <p class="def">
          {#if !awaiting}
            <span data-testid="companies">{count(opening.companies)}</span> companies changed a
            net income figure they had reported{#if opening.reporting}, of {count(opening.reporting)} reporting one that year{/if}.
          {/if}
          {#if opening.days != null}The median amendment came {count(Math.round(opening.days))} days after the figure first appeared.{/if}
        </p>
      </div>
    </div>
  </section>

  <section class="kinds prose">
    <p>
      <b>Amended (/A)</b>: the change came in an amendment, a filing that corrects an earlier one.
      <b>Changed in a later filing</b>: a later 10-Q or 10-K reported a different figure for the
      same period, as when results are recast for a sale. Companies also fix smaller errors this
      way rather than amending, so amendments are the corrections we can see for certain, not all
      of them. <b>Tag switches</b> (the company reported the figure under a different XBRL tag)
      are left out unless you include them: often the number itself did not change.
    </p>
  </section>

  <section class="controls" aria-label="Choices">
    <div class="toggle" role="group" aria-label="Which figure">
      {#each METRICS as [metric, label] (metric)}
        <button type="button" aria-pressed={s.metric === metric} onclick={() => (s.metric = metric)}>{label}</button>
      {/each}
    </div>
    <div class="toggle" role="group" aria-label="Share or count">
      <button type="button" aria-pressed={!s.counts} onclick={() => (s.counts = false)}>Share of companies</button>
      <button type="button" aria-pressed={s.counts} onclick={() => (s.counts = true)}>Count</button>
    </div>
    <label class="check">
      <input type="checkbox" bind:checked={s.tags} onchange={() => { if (!s.tags && s.kind === "tag_switch") s.kind = ""; }} />
      Include tag switches
    </label>
    {#if changed}
      <button class="clear" type="button" onclick={() => (s = { ...DEFAULT })}>Reset</button>
    {/if}
  </section>

  <section>
    <h2>Companies that changed {figure} they had reported, each year</h2>
    {#if awaiting}
      <p class="awaiting prose muted" data-testid="awaiting">These figures arrive with the next data export.</p>
    {:else}
      <RestatementsChart
        {years}
        tags={s.tags}
        counts={s.counts}
        label={s.counts ? "companies" : `% of companies reporting ${figure}`}
        selected={s.year}
        current={data.fullYear + 1}
        onselect={(year) => (s.year = year)}
      />
    {/if}
    <p class="note prose muted">
      Each company counted once a year, under its first kind of change. Shaded: {PHASE_IN[0]} to
      {PHASE_IN[1]}, when companies phased into XBRL tagging (the largest first), so even the
      shares are not comparable with later years. {data.fullYear + 1} is the year to date. Click a
      year to see its largest changes below.
    </p>
    {#if !awaiting}
      <details>
        <summary>The figures, year by year</summary>
        <div class="tablewrap">
          <table data-testid="years">
            <thead>
              <tr>
                <th scope="col">Year</th>
                {#each kinds as [kind, label] (kind)}<th scope="col">{label}</th>{/each}
                <th scope="col">Companies reporting {figure}</th>
              </tr>
            </thead>
            <tbody>
              {#each [...years].reverse() as y (y.year)}
                <tr>
                  <td>{y.year}{y.year === data.fullYear + 1 ? " (to date)" : ""}</td>
                  {#each kinds as [kind] (kind)}
                    <td>{count(y.kinds[kind]?.companies ?? 0)} <span class="muted">{percent(barValue(y, kind, false))}</span></td>
                  {/each}
                  <td>{y.reporting == null ? "—" : count(y.reporting)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </details>
    {/if}
  </section>

  <section>
    <h2>The largest changes to {figure}</h2>
    <p class="prose muted lede">
      The table holds the largest changes by dollars, and the largest amendments measured against
      the company's total assets (changes of $1m or more), so smaller companies' corrections are
      here too.
    </p>
    <div class="controls">
      <div class="toggle" role="group" aria-label="Which kind">
        <button type="button" aria-pressed={s.kind === ""} onclick={() => (s.kind = "")}>All kinds</button>
        {#each kinds as [kind, label] (kind)}
          <button type="button" aria-pressed={s.kind === kind} onclick={() => (s.kind = kind)}>{kind === "correction" ? "Amended only" : label}</button>
        {/each}
      </div>
      <label class="visually-hidden" for="restatement-order">Order</label>
      <select id="restatement-order" bind:value={s.order} disabled={!rows}>
        {#each Object.entries(ORDERS) as [value, label] (value)}<option {value}>{label}</option>{/each}
      </select>
      {#if s.year != null}
        <button class="clear" type="button" onclick={() => (s.year = null)}>{s.year} only: show every year</button>
      {/if}
    </div>
    <p class="count muted" aria-live="polite" data-testid="count">
      {#if failed}
        The full table could not load; showing the first {count(data.first.length)}. Reload to try again.
      {:else if rows}
        {count(matching.length)} {matching.length === 1 ? "change" : "changes"}{s.year != null ? ` first seen in ${s.year}` : ""}
      {:else}
        The largest {count(data.first.length)}; loading the rest.
      {/if}
    </p>
    <div class="tablewrap" data-rows={rows ? "all" : "first"}>
      <table data-testid="largest">
        <thead>
          <tr>
            <th scope="col">Company</th>
            <th scope="col">Period</th>
            <th scope="col">Kind</th>
            <th scope="col">First reported</th>
            <th scope="col">Now</th>
            <th scope="col">Change</th>
            <th scope="col">Of assets</th>
            <th scope="col">Changed</th>
          </tr>
        </thead>
        <tbody>
          {#each matching.slice(0, 200) as r (r.key)}
            <tr>
              <td data-label="Company"><a class="co" href={companyLink(r.cik)} rel={screened.has(r.cik) ? undefined : "external noopener"}>{r.name}</a></td>
              <td data-label="Period">{r.period}</td>
              <td data-label="Kind">{KIND_LABELS[r.kind] ?? r.kind}</td>
              <td data-label="First reported">{money(r.first)}</td>
              <td data-label="Now">{money(r.latest)}</td>
              <td data-label="Change" class={r.amount == null ? "" : r.amount >= 0 ? "up" : "down"}>{moneyChange(r.amount)}</td>
              <td data-label="Of assets">{percent(r.share)}</td>
              <td data-label="Changed">{r.form}, {r.days == null ? "—" : `${count(r.days)} days later`}</td>
            </tr>
          {:else}
            <tr><td colspan="8" class="empty prose">No change of this kind in the table. Pick another kind or year.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if matching.length > 200}
      <p class="muted note">Showing the first 200 of {count(matching.length)}; pick a kind or a year to narrow them.</p>
    {/if}
  </section>

  <p class="foot muted prose">
    From the SEC's Financial Statement Data Sets: each figure as first reported and as later
    reported, classified by the first filing that changed it materially (ADR 7). Likely units
    mistakes (changes of about 1,000 times) are left out.
  </p>
</main>

<style>
  .hero { padding: 48px 0 24px; border-bottom: 1px solid var(--rule); }
  h1 { font-size: clamp(28px, 4.6vw, 50px); line-height: 1.08; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 24px; max-width: 22ch; }
  .answer { display: grid; grid-template-columns: auto 1fr; gap: 6px 24px; align-items: end; max-width: 880px; }
  .n { font-size: clamp(44px, 8vw, 92px); line-height: 0.95; color: var(--accent); font-weight: 500; font-variant-numeric: tabular-nums; }
  .ctx p { margin: 0; max-width: 56ch; }
  .of { font-size: 20px; line-height: 1.3; margin-bottom: 8px !important; }
  .def { font-size: 15.5px; color: var(--muted); }
  .kinds { padding: 18px 0 4px; max-width: 80ch; font-size: 14.5px; color: var(--muted); }
  .kinds b { color: var(--text); font-weight: 500; }
  h2 { font-size: 17px; font-weight: 600; margin: 28px 0 10px; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin: 14px 0 12px; }
  .toggle { display: inline-flex; border: 1px solid var(--rule); flex-wrap: wrap; }
  .toggle button { font: inherit; font-size: 13px; background: none; color: var(--muted); border: 0; padding: 5px 12px; cursor: pointer; }
  .toggle button[aria-pressed="true"] { background: var(--accent); color: var(--on-accent); }
  select { font: inherit; font-size: 13px; background: var(--panel); color: var(--text); border: 1px solid var(--rule); padding: 5px 8px; }
  .check { font-size: 13px; display: inline-flex; gap: 6px; align-items: center; }
  .clear { font: inherit; font-size: 13px; background: none; color: var(--accent); border: 1px solid var(--accent-dim); padding: 5px 10px; cursor: pointer; }
  .note { font-size: 12.5px; max-width: 80ch; margin: 6px 0; }
  .awaiting { border: 1px solid var(--rule); background: var(--panel); padding: 48px 16px; text-align: center; margin: 0 0 8px; }
  .lede { max-width: 80ch; margin: 0 0 4px; font-size: 13.5px; }
  .count { font-size: 13px; margin: 0 0 8px; }
  details { margin: 8px 0; }
  summary { cursor: pointer; font-size: 13.5px; color: var(--accent); }
  .tablewrap { border: 1px solid var(--rule); overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
  th { background: var(--panel); color: var(--muted); font-weight: 500; text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--rule); }
  td { text-align: right; padding: 4px 8px; white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  [data-testid="largest"] th:nth-child(3), [data-testid="largest"] td:nth-child(3) { text-align: left; }
  td:first-child { white-space: normal; min-width: 18ch; }
  tbody tr:nth-child(odd) { background: var(--band); }
  .co { color: var(--text); text-decoration: none; }
  .co:hover { color: var(--accent); text-decoration: underline; }
  .empty { text-align: left; color: var(--muted); padding: 14px 12px; white-space: normal; }
  .foot { font-size: 12.5px; margin: 28px 0 40px; max-width: 80ch; }
  @media (max-width: 760px) {
    .answer { grid-template-columns: 1fr; }
    [data-testid="largest"] thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
    [data-testid="largest"], [data-testid="largest"] tbody, [data-testid="largest"] tr, [data-testid="largest"] td { display: block; }
    [data-testid="largest"] tbody tr { border: 1px solid var(--rule); margin: 0 0 8px; padding: 8px 10px; background: var(--panel) !important; }
    [data-testid="largest"] td { display: flex; justify-content: space-between; gap: 12px; padding: 2px 0; text-align: right !important; white-space: normal; }
    [data-testid="largest"] td::before { content: attr(data-label); color: var(--muted); text-align: left; }
    [data-testid="largest"] td:first-child { display: block; text-align: left !important; font-size: 14px; }
    [data-testid="largest"] td:first-child::before, .empty::before { content: none; }
    .tablewrap:has([data-testid="largest"]) { border: 0; }
  }
</style>
