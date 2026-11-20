<script>
  // One company: where it stands on the screen in both views, its quarters, its restatements and
  // its history. Everything is in the HTML; only the chart needs JavaScript.
  import { count, money, moneyChange, percent } from "#lib/format.js";
  import { link } from "#lib/pages.js";
  import { FILER_LABELS } from "#lib/screener.js";
  import QuarterChart from "#lib/components/QuarterChart.svelte";

  let { data } = $props();

  const now = $derived(data.views.latest ?? data.views.first_reported);
  const restated = $derived(data.quarters.filter((q) => q.niRestated || q.cashRestated));
  const edgar = $derived(`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${data.cik}&type=10-&dateb=&owner=include&count=40`);
  /** @type {[string, string][]} */
  const VIEWS = [
    ["latest", "After restatements"],
    ["first_reported", "As first reported"],
  ];
  /** @param {number | null} v */
  const signed = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${percent(Math.abs(v))}`);
  const METRIC = /** @type {Record<string, string>} */ ({ net_income: "Net income", operating_cash_flow: "Operating cash flow" });
</script>

<svelte:head>
  <title>{now.name}: EarningsWatch</title>
  <meta name="description" content="{now.name}: net income against operating cash flow, restatements and history, from SEC filings." />
</svelte:head>

<main>
  <header class="head">
    <p class="crumb"><a href={link("/screener")}>Screener</a> / CIK {data.cik}</p>
    <h1>{now.name}</h1>
    <p class="meta">
      {now.industry}, {(FILER_LABELS[now.filer] ?? now.filer).toLowerCase()} filer. Latest quarter
      {now.quarter}, filed {now.filed}.
    </p>
    <p class="tags">
      {#if data.views.latest?.flagged}<span class="tag flag">Flagged after restatements</span>{/if}
      {#if data.views.first_reported?.flagged}<span class="tag flag">Flagged as first reported</span>{/if}
      {#if now.implausible}<span class="tag check">Check filing</span>{/if}
      {#if now.behind}<span class="tag">Behind on filings</span>{/if}
    </p>
    {#if now.implausible}
      <p class="warn prose" data-testid="implausible">
        Net income or operating cash flow over the year is more than twice this company's total
        assets. That is almost always a units mistake in the filing's tagging (thousands taken as
        units), not a real result: check the filing before relying on these figures.
      </p>
    {/if}
    {#if now.behind}
      <p class="warn prose">
        This company's latest quarter ({now.quarter}) is more than two quarters before most
        companies'. It is left out of the screener's default view and the overview's counts.
      </p>
    {/if}
  </header>

  <section>
    <h2>Trailing twelve months, against the twelve before</h2>
    <div class="tablewrap">
      <table class="snapshot">
        <thead>
          <tr><th scope="col"></th>{#each VIEWS as [key, label] (key)}{#if data.views[key]}<th scope="col">{label}</th>{/if}{/each}</tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Net income</th>
            {#each VIEWS as [key] (key)}{@const r = data.views[key]}{#if r}<td>{money(r.ni)} <span class="muted">from {money(r.niPrior)}</span></td>{/if}{/each}
          </tr>
          <tr>
            <th scope="row">Growth</th>
            {#each VIEWS as [key] (key)}{@const r = data.views[key]}{#if r}<td>{r.growth == null ? "no positive base a year ago" : signed(r.growth)}</td>{/if}{/each}
          </tr>
          <tr>
            <th scope="row">Income change / assets</th>
            {#each VIEWS as [key] (key)}{@const r = data.views[key]}{#if r}<td class={r.change == null ? "" : r.change >= 0 ? "up" : "down"}>{signed(r.change)}</td>{/if}{/each}
          </tr>
          <tr>
            <th scope="row">Operating cash flow</th>
            {#each VIEWS as [key] (key)}{@const r = data.views[key]}{#if r}<td>{money(r.cash)} <span class="muted">from {money(r.cashPrior)}</span></td>{/if}{/each}
          </tr>
          <tr>
            <th scope="row">Gap (income minus cash)</th>
            {#each VIEWS as [key] (key)}{@const r = data.views[key]}{#if r}<td>{money(r.accruals)}</td>{/if}{/each}
          </tr>
          <tr>
            <th scope="row">Gap / assets</th>
            {#each VIEWS as [key] (key)}{@const r = data.views[key]}{#if r}<td>{percent(r.gap)} <span class="muted">of {money(r.assets)}</span></td>{/if}{/each}
          </tr>
          <tr>
            <th scope="row">Flagged</th>
            {#each VIEWS as [key] (key)}{@const r = data.views[key]}{#if r}<td>{r.flagged ? "Yes" : "No"}</td>{/if}{/each}
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Quarter by quarter</h2>
    <p class="prose muted lede">
      Three-month figures, after restatements. An open circle is net income as first reported, in
      a quarter later restated.
    </p>
    <QuarterChart quarters={data.quarters} />
    <details>
      <summary>Every quarter's figures ({count(data.quarters.length)})</summary>
      <div class="tablewrap">
        <table data-testid="quarters">
          <thead>
            <tr>
              <th scope="col">Quarter end</th>
              <th scope="col">Net income</th>
              <th scope="col">First reported</th>
              <th scope="col">Operating cash</th>
              <th scope="col">First reported</th>
            </tr>
          </thead>
          <tbody>
            {#each [...data.quarters].reverse() as q (q.end)}
              <tr>
                <td>{q.end}{#if q.derived}<span class="muted" title="Derived: the year less its first three quarters"> *</span>{/if}</td>
                <td>{money(q.niLatest)}</td>
                <td class={q.niRestated ? "restated" : "muted"}>{q.niRestated ? money(q.niFirst) : "same"}</td>
                <td>{money(q.cashLatest)}</td>
                <td class={q.cashRestated ? "restated" : "muted"}>{q.cashRestated ? money(q.cashFirst) : "same"}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <p class="muted note">* Derived: a fourth quarter, the year's figure less the first three quarters'.</p>
    </details>
  </section>

  <section>
    <h2>Restatements</h2>
    {#if restated.length}
      <p class="prose lede">
        {count(restated.length)} of its {count(data.quarters.length)} quarters were restated: a later
        filing changed net income or operating cash flow it had already reported.
      </p>
    {:else}
      <p class="prose lede">None: every quarter's figures are as first reported.</p>
    {/if}
    {#if data.restatements.length}
      <div class="tablewrap">
        <table data-testid="largest">
          <caption class="muted">Among the largest restatements across all companies</caption>
          <thead>
            <tr>
              <th scope="col">Period end</th>
              <th scope="col">Figure</th>
              <th scope="col">Kind</th>
              <th scope="col">First reported</th>
              <th scope="col">Latest</th>
              <th scope="col">Change</th>
              <th scope="col">Changed by</th>
            </tr>
          </thead>
          <tbody>
            {#each data.restatements as r (r.metric + r.end)}
              <tr>
                <td>{r.end}</td>
                <td>{METRIC[r.metric] ?? r.metric}</td>
                <td>{r.kind.replaceAll("_", " ")}</td>
                <td>{money(r.first)}</td>
                <td>{money(r.latest)}</td>
                <td>{r.latest != null && r.first != null ? moneyChange(r.latest - r.first) : "—"} <span class="muted">{signed(r.pct)}</span></td>
                <td>{r.form}, {count(r.days)} days later</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <section>
    <h2>History</h2>
    <div class="tablewrap">
      <table class="texts" data-testid="history">
        <thead>
          <tr><th scope="col">From</th><th scope="col">Until</th><th scope="col">Name</th><th scope="col">Industry</th><th scope="col">Filer status</th></tr>
        </thead>
        <tbody>
          {#each data.history as h (h.from)}
            <tr><td>{h.from}</td><td>{h.to ?? "now"}</td><td>{h.name}</td><td>{h.industry ?? "—"}</td><td>{h.filer ?? "—"}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  <p class="foot prose muted">
    From the SEC's Financial Statement Data Sets. <a href={edgar} rel="external noopener">This company's filings on EDGAR</a>.
    A screen for where to look harder, not investment advice.
  </p>
</main>

<style>
  .head { padding: 32px 0 8px; }
  .crumb { font-size: 13px; color: var(--muted); margin: 0 0 8px; }
  h1 { font-size: clamp(26px, 4vw, 40px); margin: 0 0 6px; letter-spacing: -0.015em; font-weight: 600; }
  h2 { font-size: 17px; font-weight: 600; margin: 32px 0 8px; }
  .meta { color: var(--muted); font-size: 13.5px; margin: 0 0 8px; }
  .tags { margin: 0 0 8px; }
  .tags .tag:first-child { margin-left: 0; }
  .warn { border-left: 3px solid var(--text); padding: 6px 12px; max-width: 72ch; margin: 10px 0; background: var(--panel); }
  .lede { max-width: 72ch; margin: 0 0 12px; }
  .tablewrap { overflow-x: auto; border: 1px solid var(--rule); margin: 8px 0; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
  caption { text-align: left; font-size: 12.5px; padding: 6px 10px; }
  th, td { padding: 4px 10px; text-align: right; white-space: nowrap; }
  thead th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--rule); background: var(--panel); }
  th:first-child, td:first-child, tbody th { text-align: left; }
  tbody th { font-weight: 400; color: var(--muted); }
  tbody tr:nth-child(odd) { background: var(--band); }
  .snapshot td { min-width: 22ch; }
  .texts th, .texts td { text-align: left; }
  .restated { color: var(--text); font-weight: 600; }
  details { margin: 10px 0; }
  summary { cursor: pointer; font-size: 13.5px; color: var(--accent); }
  .note { font-size: 12px; }
  .foot { font-size: 12.5px; margin: 32px 0 40px; }
</style>
