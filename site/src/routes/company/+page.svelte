<script>
  // Find a company: the flagged ones are listed (readable without JavaScript); search by name
  // or CIK finds any company the screener covers.
  import { count } from "#lib/format.js";
  import { link } from "#lib/pages.js";

  let { data } = $props();
  let query = $state("");

  const flagged = $derived(data.companies.filter((c) => c.flagged && !c.behind));
  const matches = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return null;
    return data.companies.filter((c) => c.name.toLowerCase().includes(q) || String(c.cik) === q).slice(0, 50);
  });
</script>

<svelte:head>
  <title>Company: EarningsWatch</title>
</svelte:head>

<main>
  <section class="head">
    <h1>Company</h1>
    <p class="prose lede">
      One company at a time: its quarterly net income against operating cash flow, as first
      reported and after restatements, and its names and industries over the years. Search any
      of the {count(data.companies.length)} companies the screener covers, by name or CIK.
    </p>
    <label class="visually-hidden" for="company-find">Find a company</label>
    <input id="company-find" class="search" type="search" placeholder="Company name or CIK" data-search bind:value={query} />
  </section>

  {#if matches}
    <h2>{count(matches.length)}{matches.length === 50 ? "+" : ""} {matches.length === 1 ? "match" : "matches"}</h2>
    <ul class="list">
      {#each matches as c (c.cik)}
        <li>
          <a href="{link("/company")}{c.cik}/">{c.name}</a>
          <span class="muted">{c.cik}</span>
          {#if c.flagged}<span class="tag flag">Flagged</span>{/if}
          {#if c.behind}<span class="tag">Behind on filings</span>{/if}
        </li>
      {:else}
        <li class="muted prose">No company by that name or CIK. The screener covers companies still filing, with at least $10m of assets, outside finance.</li>
      {/each}
    </ul>
  {:else}
    <h2>Flagged now, after restatements</h2>
    <ul class="list">
      {#each flagged as c (c.cik)}
        <li><a href="{link("/company")}{c.cik}/">{c.name}</a> <span class="muted">{c.cik}</span></li>
      {/each}
    </ul>
  {/if}
</main>

<style>
  .head { padding: 40px 0 8px; }
  h1 { font-size: clamp(28px, 4.4vw, 44px); margin: 0 0 10px; letter-spacing: -0.015em; font-weight: 600; }
  h2 { font-size: 15px; font-weight: 600; margin: 24px 0 8px; }
  .lede { color: var(--muted); max-width: 70ch; margin: 0 0 18px; }
  .search {
    font: inherit; font-size: 14px; background: var(--panel); color: var(--text);
    border: 1px solid var(--rule); padding: 7px 10px; width: min(100%, 420px);
  }
  .list { list-style: none; padding: 0; margin: 0 0 40px; columns: 2 320px; column-gap: 32px; font-size: 13.5px; }
  .list li { padding: 3px 0; break-inside: avoid; }
  .list a { color: var(--text); }
  .list a:hover { color: var(--accent); }
</style>
