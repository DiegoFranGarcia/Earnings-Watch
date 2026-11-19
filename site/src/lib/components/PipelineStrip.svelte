<script>
  import { utcTime } from "#lib/format.js";

  /** @type {{ pipeline: any, exportedAt: string }} */
  let { pipeline, exportedAt } = $props();
</script>

<section class="section">
  <h2>How these numbers get here</h2>
  <p class="lede prose">
    Every morning the pipeline downloads new filings, rebuilds and tests the models, and republishes
    this site. If any test fails, the site keeps its last good data.
  </p>
  <ol class="path">
    <li><b>SEC EDGAR</b><span>filings, daily</span></li>
    <li><b>S3</b><span>raw files, as published</span></li>
    <li><b>Spark on EMR</b><span>parsed to Parquet</span></li>
    <li><b>Snowflake</b><span>loaded</span></li>
    <li><b>dbt</b><span>{pipeline.tests_passed == null ? "models and tests" : `${pipeline.tests_passed} tests passed`}</span></li>
    <li class="live"><b>This site</b><span>{utcTime(exportedAt)} on {exportedAt.slice(0, 10)}</span></li>
  </ol>
</section>

<style>
  .section { padding: 36px 0 8px; }
  h2 { font-size: 18px; font-weight: 600; margin: 0 0 6px; }
  .lede { color: var(--muted); margin: 0 0 16px; max-width: 64ch; }
  .path { display: flex; flex-wrap: wrap; list-style: none; padding: 0; margin: 4px 0 0; font-size: 13px; }
  li { border: 1px solid var(--rule); margin: -1px 0 0 -1px; padding: 10px 14px; min-width: 132px; }
  b { display: block; font-weight: 500; }
  span { color: var(--muted); }
  .live b { color: var(--accent); }
</style>
