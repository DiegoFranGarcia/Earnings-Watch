<script>
  // The overview's picture of the pipeline: six stages in order, and the check that decides
  // whether this site changes at all. The full architecture (Airflow, the gates, each stage's
  // code) belongs to the Pipeline page.
  import { utcTime } from "#lib/format.js";
  import { link } from "#lib/pages.js";

  /** @type {{ exportedAt: string }} */
  let { exportedAt } = $props();
</script>

<section class="section">
  <h2>How these numbers get here</h2>
  <p class="lede prose">
    Every morning the pipeline downloads new filings, rebuilds and tests the models, and republishes
    this site. If any test fails, the site keeps its last good data.
  </p>
  <ol class="flow">
    <li class="stage"><b>SEC EDGAR</b><span>filings, daily</span></li>
    <li class="stage"><b>S3</b><span>raw files, as published</span></li>
    <li class="stage"><b>Spark on EMR</b><span>parsed to Parquet</span></li>
    <li class="stage"><b>Snowflake</b><span>loaded</span></li>
    <li class="stage"><b>dbt</b><span>models built and tested</span></li>
    <li class="gate">
      <b>Every check passes?</b>
      <span>Yes: publish.</span>
      <span>No: this site keeps its last good data.</span>
    </li>
    <li class="stage live"><b>This site</b><span>{utcTime(exportedAt)} on {exportedAt.slice(0, 10)}</span></li>
  </ol>
  <p class="more"><a href={link("/pipeline")}>See the full pipeline</a></p>
</section>

<style>
  .section { padding: 36px 0 8px; }
  h2 { font-size: 18px; font-weight: 600; margin: 0 0 6px; }
  .lede { color: var(--muted); margin: 0 0 16px; max-width: 64ch; }

  /* Left to right on a wide screen, an arrow between each step; top to bottom on a narrow one. */
  .flow {
    display: flex; align-items: stretch; gap: 22px;
    list-style: none; padding: 0; margin: 4px 0 0; font-size: 13px;
  }
  .flow > li { position: relative; flex: 1 1 0; min-width: 0; padding: 10px 12px; }
  /* The arrows are drawn, not read aloud (the empty alternative text after the slash). */
  .flow > li + li::before {
    content: "→" / ""; position: absolute; left: -18px; top: 50%; transform: translateY(-50%);
    color: var(--accent); font-size: 17px; line-height: 1;
  }
  .stage { border: 1px solid var(--rule); background: var(--panel); }
  b { display: block; font-weight: 500; }
  span { display: block; color: var(--muted); }
  .live { border-color: var(--accent-dim); }
  .live b { color: var(--accent); }

  /* The checkpoint: not a stage but the question every run must answer before this site changes. */
  .gate { flex-grow: 1.9; border: 1px dashed var(--accent); }
  .gate b { color: var(--accent); }
  .gate span + span { margin-top: 4px; }

  .more { margin: 14px 0 0; font-size: 13px; }

  @media (max-width: 1040px) {
    .flow { flex-direction: column; gap: 22px; }
    .flow > li + li::before { content: "↓" / ""; left: 14px; top: -20px; transform: none; }
  }
</style>
