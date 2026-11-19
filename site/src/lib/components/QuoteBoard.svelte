<script>
  import { cents, compact } from "#lib/format.js";
  import { link } from "#lib/pages.js";

  /** @type {{ facts: any, dollars30d: number }} */
  let { facts, dollars30d } = $props();
  const repo = "https://github.com/DiegoFranGarcia/Earnings-Watch/blob/main/";
</script>

<section class="board" aria-label="The data behind it">
  <div class="quote">
    <span class="what">
      Numbers read from {facts.numbers_read.years} years of SEC filings, {facts.numbers_read.lines_lost} lines lost
      <a href="{repo}{facts.numbers_read.source}">measured</a>
    </span>
    <span class="v">{compact(facts.numbers_read.value)}</span>
  </div>
  <div class="quote">
    <span class="what">
      Quarter checks where Spark matches the DuckDB reference row for row
      <a href="{repo}{facts.parity.source}">measured</a>
    </span>
    <span class="v">{facts.parity.matched} / {facts.parity.checks}</span>
  </div>
  <div class="quote">
    <span class="what">
      Snowflake and Spark compute, last 30 days
      <a href={link("/pipeline")}>by day</a>
    </span>
    <span class="v">{cents(dollars30d)}</span>
  </div>
</section>

<style>
  .board { display: grid; grid-template-columns: repeat(3, 1fr); border-bottom: 1px solid var(--rule); }
  .quote {
    padding: 18px 18px 18px 0; display: flex; justify-content: space-between; gap: 12px;
    border-right: 1px solid var(--rule);
  }
  .quote + .quote { padding-left: 18px; }
  .quote:last-child { border-right: 0; }
  .what { color: var(--muted); font-size: 13px; max-width: 26ch; }
  .what a { display: block; font-size: 12px; margin-top: 2px; }
  .v { font-size: 22px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  @media (max-width: 760px) {
    .board { grid-template-columns: 1fr; }
    .quote, .quote + .quote { border-right: 0; border-bottom: 1px solid var(--rule); padding: 14px 0; }
  }
</style>
