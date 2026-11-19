<script>
  import { dbtDocs } from "#lib/pages.js";
  import FlaggedTable from "#lib/components/FlaggedTable.svelte";
  import Hero from "#lib/components/Hero.svelte";
  import PipelineStrip from "#lib/components/PipelineStrip.svelte";
  import QuoteBoard from "#lib/components/QuoteBoard.svelte";

  let { data } = $props();
  let view = $state("latest");
</script>

<svelte:head>
  <title>EarningsWatch: profits their cash doesn't back up</title>
  <meta name="description" content="A daily screen of US public companies whose rising profits their operating cash flow doesn't back up, built from SEC filings by a tested data pipeline." />
</svelte:head>

<main>
  <Hero summary={data.overview.summary} {view} onview={(v) => (view = v)} />
  <QuoteBoard facts={data.facts} dollars30d={data.overview.pipeline.dollars_30d} />
  <FlaggedTable rows={data.overview.rows} industries={data.overview.industries} {view} />
  <PipelineStrip pipeline={data.overview.pipeline} exportedAt={data.status.exported_at} />
  <footer class="muted">
    <p>A screen for where to look harder, not investment advice. Source: SEC Financial Statement Data Sets.</p>
    <p>
      <a href="https://github.com/DiegoFranGarcia/Earnings-Watch">Source code</a>&emsp;<a href={dbtDocs()} data-sveltekit-reload>dbt docs</a>
    </p>
  </footer>
</main>

<style>
  footer { font-size: 12.5px; padding: 28px 0 40px; }
</style>
