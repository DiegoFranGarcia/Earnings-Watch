<script>
  import { count, growth, money, moneyChange, percent } from "#lib/format.js";
  import { link } from "#lib/pages.js";
  import Spark from "./Spark.svelte";

  /** @type {{ rows: any[], industries: string[], view: string }} */
  let { rows, industries, view } = $props();
  let industry = $state("");
  let query = $state("");

  const shown = $derived(
    rows.filter(
      (r) =>
        r.view === view &&
        (!industry || r.industry === industry) &&
        (!query || r.name.toLowerCase().includes(query.trim().toLowerCase())),
    ),
  );
  const total = $derived(rows.filter((r) => r.view === view).length);
</script>

<section class="section">
  <h2>The flagged companies</h2>
  <p class="lede prose">
    Trailing twelve months, with the change on the year before, largest gap first. Click a company
    for its quarters, restatements and history, or press 1 for the full screener.
  </p>
  <div class="filters">
    <label class="visually-hidden" for="company-search">Search a company</label>
    <input id="company-search" class="search" type="search" placeholder="Search a company" data-search bind:value={query} />
    <button class="chip" type="button" aria-pressed={industry === ""} onclick={() => (industry = "")}>All industries</button>
    {#each industries as name (name)}
      <button class="chip" type="button" aria-pressed={industry === name} onclick={() => (industry = name)}>{name}</button>
    {/each}
  </div>
  <p class="shown muted" aria-live="polite">Showing {count(shown.length)} of {count(total)}</p>
  <div class="tablewrap">
    <table>
      <thead>
        <tr>
          <th scope="col">Company</th>
          <th scope="col" class="hide-sm">Industry</th>
          <th scope="col">Net income</th>
          <th scope="col" class="hide-sm">Operating cash</th>
          <th scope="col">Gap / assets</th>
          <th scope="col" class="hide-sm">8 quarters</th>
          <th scope="col" class="hide-sm">Quarter</th>
        </tr>
      </thead>
      <tbody>
        {#each shown as r (r.cik + r.view)}
          {@const g = growth(r.net_income, r.net_income_prior)}
          <tr>
            <td><a class="co" href="{link("/company")}?cik={r.cik}">{r.name}</a></td>
            <td class="hide-sm">{r.industry}</td>
            <td>{money(r.net_income)} {#if g != null}<span class="up">+{g}%</span>{/if}</td>
            <td class="hide-sm">
              {money(r.cash)}
              <span class={r.cash - r.cash_prior >= 0 ? "up" : "down"}>{moneyChange(r.cash - r.cash_prior)}</span>
            </td>
            <td>{percent(r.gap)}</td>
            <td class="hide-sm"><Spark values={r.series} label="Net income, last {r.series.length} quarters" /></td>
            <td class="hide-sm">{r.quarter}</td>
          </tr>
        {:else}
          <tr><td colspan="7" class="empty prose">No flagged company matches. Clear the search or pick another industry.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

<style>
  .section { padding: 36px 0 8px; }
  h2 { font-size: 18px; font-weight: 600; margin: 0 0 6px; }
  .lede { color: var(--muted); margin: 0 0 16px; max-width: 64ch; }
  .filters { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 8px; }
  .chip {
    font: inherit; font-size: 12.5px; color: var(--text); background: none;
    border: 1px solid var(--rule); padding: 4px 10px; cursor: pointer;
  }
  .chip[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }
  .search {
    font: inherit; font-size: 13px; background: var(--panel); color: var(--text);
    border: 1px solid var(--rule); padding: 4px 10px; min-width: 220px;
  }
  .shown { font-size: 12.5px; margin: 0 0 8px; }
  .tablewrap { overflow-x: auto; border: 1px solid var(--rule); max-height: 560px; overflow-y: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
  th {
    position: sticky; top: 0; background: var(--panel); text-align: right; font-weight: 500;
    color: var(--muted); padding: 6px 12px; border-bottom: 1px solid var(--rule); white-space: nowrap;
  }
  td { text-align: right; padding: 4px 12px; white-space: nowrap; line-height: 1.35; }
  th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
  tbody tr:nth-child(odd) { background: var(--band); }
  tbody tr:hover { outline: 1px solid var(--accent-dim); outline-offset: -1px; }
  .co { color: var(--text); text-decoration: none; }
  .co:hover { color: var(--accent); text-decoration: underline; }
  .empty { text-align: left; color: var(--muted); padding: 14px 12px; white-space: normal; }
  @media (max-width: 760px) {
    td:first-child { white-space: normal; }
  }
</style>
