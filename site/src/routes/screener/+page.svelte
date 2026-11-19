<script>
  // The screener. Its HTML holds the first rows (readable without JavaScript); the browser then
  // loads every row from the export's Parquet, and filters, sorts and selects there, keeping the
  // choices in the page's address.
  import { onMount } from "svelte";
  import { replaceState } from "$app/navigation";
  import { count, money, moneyChange, percent } from "#lib/format.js";
  import { link } from "#lib/pages.js";
  import { readParquet } from "#lib/parquet.js";
  import ScreenerScatter from "#lib/components/ScreenerScatter.svelte";
  import {
    DEFAULT,
    FILERS,
    FILER_LABELS,
    PAGE,
    SORTS,
    filterRows,
    parseState,
    sortRows,
    toRow,
    toSearch,
  } from "#lib/screener.js";

  let { data } = $props();

  /** Every row, once loaded. @type {import("#lib/screener.js").Row[] | null} */
  let rows = $state.raw(null);
  let failed = $state(false);
  /** @type {import("#lib/screener.js").State} */
  let s = $state({ ...DEFAULT });
  let shown = $state(PAGE);
  /** @type {number | null} */
  let hovered = $state(null);
  let ready = $state(false);

  const matching = $derived(rows ? sortRows(filterRows(rows, s), s.sort, s.dir) : data.first);
  // The chart shows every company the other choices allow, so an area can be chosen among them.
  const charted = $derived(rows ? filterRows(rows, { ...s, growth: null, gap: null }) : null);
  const universe = $derived(data.summary[s.view].universe);
  const changed = $derived(toSearch(s) !== "");

  /** @type {Record<string, string>} */
  const HEADERS = {
    name: "Company",
    industry: "Industry",
    filer: "Filer size",
    ni: "Net income",
    growth: "Growth",
    cash: "Operating cash",
    gap: "Gap / assets",
    quarter: "Quarter",
  };

  onMount(() => {
    s = parseState(new URL(location.href).searchParams);
    ready = true;
    (async () => {
      try {
        const response = await fetch(`${link("/")}data/export_screener.parquet`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        rows = (await readParquet(await response.arrayBuffer())).map(toRow);
      } catch {
        failed = true;
      }
    })();
  });

  // The choices, in the address (so a view can be shared), and back to the first page of rows.
  $effect(() => {
    const search = toSearch(s);
    shown = PAGE;
    if (ready) replaceState(`${location.pathname}${search}`, {});
  });

  /** @param {string} key */
  function sortBy(key) {
    if (s.sort === key) s.dir = s.dir === "asc" ? "desc" : "asc";
    else {
      s.sort = key;
      s.dir = SORTS[/** @type {keyof typeof SORTS} */ (key)];
    }
  }

  /** @param {string} key */
  const ariaSort = (key) => (s.sort === key ? (s.dir === "asc" ? "ascending" : "descending") : undefined);
</script>

<svelte:head>
  <title>Screener: EarningsWatch</title>
  <meta name="description" content="Every US public company the EarningsWatch screen covers: net income against operating cash flow, filterable by industry and filer size." />
</svelte:head>

<main>
  <header class="head">
    <h1>Screener</h1>
    <p class="prose lede">
      Every company still filing that the screen covers, at its latest quarter: trailing twelve
      months against the twelve before. Filter and sort the table, or drag across the chart to
      keep the companies in one area. The address keeps your choices, so you can share them.
    </p>
  </header>

  <section class="controls" aria-label="Filters">
    <div class="viewtoggle" role="group" aria-label="Which figures">
      <button type="button" aria-pressed={s.view === "latest"} onclick={() => (s.view = "latest")}>After restatements</button>
      <button type="button" aria-pressed={s.view === "first_reported"} onclick={() => (s.view = "first_reported")}>As first reported</button>
    </div>
    <label class="visually-hidden" for="screener-search">Search a company</label>
    <input id="screener-search" class="search" type="search" placeholder="Search a company or CIK" data-search disabled={!rows} bind:value={s.q} />
    <label class="visually-hidden" for="screener-industry">Industry</label>
    <select id="screener-industry" disabled={!rows} bind:value={s.industry}>
      <option value="">All industries</option>
      {#each data.industries as name (name)}<option value={name}>{name}</option>{/each}
    </select>
    <label class="visually-hidden" for="screener-filer">Filer size</label>
    <select id="screener-filer" disabled={!rows} bind:value={s.filer}>
      <option value="">All filer sizes</option>
      {#each FILERS as [value, label] (value)}<option {value}>{label}</option>{/each}
    </select>
    <label class="check"><input type="checkbox" disabled={!rows} bind:checked={s.flagged} /> Flagged only</label>
    <label class="visually-hidden" for="screener-sort">Sort by</label>
    <select id="screener-sort" class="show-sm" disabled={!rows} value={`${s.sort} ${s.dir}`} onchange={(e) => {
      const [sort, dir] = e.currentTarget.value.split(" ");
      s.sort = sort;
      s.dir = /** @type {"asc" | "desc"} */ (dir);
    }}>
      {#each Object.entries(HEADERS) as [key, label] (key)}
        <option value="{key} desc">{label}, high to low</option>
        <option value="{key} asc">{label}, low to high</option>
      {/each}
    </select>
    {#if changed}
      <button class="clear" type="button" onclick={() => (s = { ...DEFAULT })}>Clear filters</button>
    {/if}
  </section>

  <ScreenerScatter
    rows={charted}
    selection={{ growth: s.growth, gap: s.gap }}
    {hovered}
    onselect={(area) => {
      s.growth = area?.growth ?? null;
      s.gap = area?.gap ?? null;
    }}
  />

  <p class="count" aria-live="polite" data-testid="count">
    {#if failed}
      The full table could not load. Showing the first {count(data.first.length)} companies; reload to try again.
    {:else if rows}
      {count(matching.length)} of {count(universe)} companies{#if s.growth || s.gap}, in the selected area{/if}
    {:else}
      The first {count(data.first.length)} of {count(universe)} companies, largest gap first. Loading the rest.
    {/if}
  </p>

  <div class="tablewrap" data-rows={rows ? "all" : "first"}>
    <table>
      <thead>
        <tr>
          {#each Object.entries(HEADERS) as [key, label] (key)}
            <th scope="col" aria-sort={ariaSort(key)}>
              <button type="button" disabled={!rows} onclick={() => sortBy(key)}>
                {label}<span class="arrow" aria-hidden="true">{s.sort === key ? (s.dir === "asc" ? "▲" : "▼") : ""}</span>
              </button>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each matching.slice(0, shown) as r (r.cik)}
          {@const cashChange = r.cash != null && r.cashPrior != null ? r.cash - r.cashPrior : null}
          <tr onmouseenter={() => (hovered = r.cik)} onmouseleave={() => (hovered = null)}>
            <td data-label="Company">
              <a class="co" href="{link("/company")}?cik={r.cik}">{r.name}</a>
              {#if r.flagged}<span class="flag">Flagged</span>{/if}
            </td>
            <td data-label="Industry"><span>{r.industry}</span></td>
            <td data-label="Filer size"><span>{FILER_LABELS[r.filer] ?? r.filer}</span></td>
            <td data-label="Net income"><span>{money(r.ni)}</span></td>
            <td data-label="Growth" class={r.growth == null ? "" : r.growth >= 0 ? "up" : "down"}>
              <span>{r.growth == null ? "—" : `${r.growth >= 0 ? "+" : "−"}${percent(Math.abs(r.growth), 0)}`}</span>
            </td>
            <td data-label="Operating cash">
              <span>{money(r.cash)}{#if cashChange != null}<span class="chg {cashChange >= 0 ? "up" : "down"}">{moneyChange(cashChange)}</span>{/if}</span>
            </td>
            <td data-label="Gap / assets"><span>{percent(r.gap)}</span></td>
            <td data-label="Quarter"><span>{r.quarter}</span></td>
          </tr>
        {:else}
          <tr><td colspan="8" class="empty prose">No company matches. Clear a filter, or the selected area, to see more.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
  {#if matching.length > shown}
    <button class="more" type="button" onclick={() => (shown += PAGE)}>
      Show {count(Math.min(PAGE, matching.length - shown))} more ({count(matching.length - shown)} left)
    </button>
  {/if}
  <p class="foot muted prose">
    Growth is shown only from a positive base. Flagged: net income up on a year ago, operating cash
    flow not, and the gap above 10% of total assets. A screen for where to look harder, not
    investment advice.
  </p>
</main>

<style>
  .head { padding: 40px 0 8px; }
  h1 { font-size: clamp(28px, 4.4vw, 44px); margin: 0 0 10px; letter-spacing: -0.015em; font-weight: 600; }
  .lede { color: var(--muted); max-width: 70ch; margin: 0 0 20px; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 0 0 16px; }
  .viewtoggle { display: inline-flex; border: 1px solid var(--rule); }
  .viewtoggle button {
    font: inherit; font-size: 13px; background: none; color: var(--muted); border: 0;
    padding: 5px 12px; cursor: pointer;
  }
  .viewtoggle button[aria-pressed="true"] { background: var(--accent); color: var(--on-accent); }
  .search, select {
    font: inherit; font-size: 13px; background: var(--panel); color: var(--text);
    border: 1px solid var(--rule); padding: 5px 8px;
  }
  .search { min-width: 220px; }
  .check { font-size: 13px; display: inline-flex; gap: 6px; align-items: center; }
  .clear, .more {
    font: inherit; font-size: 13px; background: none; color: var(--accent);
    border: 1px solid var(--accent-dim); padding: 5px 10px; cursor: pointer;
  }
  .show-sm { display: none; }
  .count { font-size: 13px; color: var(--muted); margin: 0 0 8px; }
  .tablewrap { border: 1px solid var(--rule); overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
  th { position: sticky; top: 0; background: var(--panel); border-bottom: 1px solid var(--rule); text-align: right; }
  th button {
    font: inherit; font-weight: 500; color: var(--muted); background: none; border: 0;
    padding: 6px 8px; cursor: pointer; white-space: nowrap; width: 100%; text-align: inherit;
  }
  th[aria-sort] button { color: var(--accent); }
  .arrow { display: inline-block; width: 1.2em; font-size: 10px; text-align: center; }
  td { text-align: right; padding: 4px 8px; white-space: nowrap; line-height: 1.35; }
  th:nth-child(-n + 3), td:nth-child(-n + 3) { text-align: left; }
  tbody tr:nth-child(odd) { background: var(--band); }
  tbody tr:hover { outline: 1px solid var(--accent-dim); outline-offset: -1px; }
  .chg { margin-left: 6px; }
  .co { color: var(--text); text-decoration: none; }
  .co:hover { color: var(--accent); text-decoration: underline; }
  .flag { margin-left: 6px; font-size: 11px; color: var(--accent); border: 1px solid var(--accent-dim); padding: 0 4px; }
  .empty { text-align: left; color: var(--muted); padding: 14px 12px; white-space: normal; }
  .more { margin-top: 10px; }
  .foot { font-size: 12.5px; margin: 18px 0 40px; max-width: 80ch; }

  /* On a phone, each company is a card: its name, then each figure with its label. */
  @media (max-width: 760px) {
    .show-sm { display: inline-block; }
    .search { min-width: 0; flex: 1 1 100%; }
    .tablewrap { border: 0; overflow: visible; }
    thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
    table, tbody, tr, td { display: block; }
    tbody tr { border: 1px solid var(--rule); margin: 0 0 8px; padding: 8px 10px; background: var(--panel) !important; }
    td { display: flex; justify-content: space-between; gap: 12px; padding: 2px 0; text-align: right !important; white-space: normal; }
    td::before { content: attr(data-label); color: var(--muted); text-align: left; }
    td:first-child { display: block; text-align: left !important; font-size: 14px; margin-bottom: 4px; }
    td:first-child::before { content: none; }
    .empty::before { content: none; }
  }
</style>
