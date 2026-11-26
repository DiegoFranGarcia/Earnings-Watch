<script>
  // The pipeline's complete record: every morning since it began, how often it was on time, when
  // it stopped itself, what it cost, what went wrong, and how it works. Absolute dates only, so the
  // page reads correctly while the pipeline runs and after it has stopped (RETIRED_ON).
  import { cents, percent } from "#lib/format.js";
  import PipelineCalendar from "#lib/components/PipelineCalendar.svelte";
  import PipelineDiagram from "#lib/components/PipelineDiagram.svelte";
  import {
    ALSO_COVERED, COST_COVERS, EVENTS, FAULT_DRILLS, RETIRED_ON, STATES, longDate, stateLabel, statusLine,
    tense, times,
  } from "#lib/pipeline.js";

  let { data } = $props();
  const s = $derived(data.summary);
  const KINDS = { incident: "Incident", drill: "Fault drill", recovery: "Recovery drill" };
</script>

<svelte:head>
  <title>Pipeline: EarningsWatch</title>
  <meta name="description" content="The EarningsWatch pipeline's complete record: every morning since it began, how often it exported on time, when it stopped itself rather than publish, and what it costs." />
</svelte:head>

<main>
  <section class="hero">
    <h1>The pipeline's record</h1>
    {#if s.first}
      <p class="status" data-testid="status">{statusLine(s.first, RETIRED_ON)}</p>
    {:else}
      <p class="status" data-testid="status">No days recorded yet.</p>
    {/if}
  </section>

  {#if s.first}
    <section class="figures" aria-label="The record in three numbers">
      <div class="fig">
        <span class="n" data-testid="on-time">{percent(s.onTimeShare, 0)}</span>
        <span class="what prose">
          Exported by 09:00 UTC on {s.onTime} of {s.due} mornings a run was due.
        </span>
      </div>
      <div class="fig">
        <span class="n" data-testid="held">{s.held}</span>
        <span class="what prose">
          {#if s.held === 0}
            {tense("Has never", "Never")} held back its export: no check has failed.
          {:else}
            {tense("Has held", "Held")} back its export {times(s.held)} when a check failed, rather than
            publish.
          {/if}
          And {FAULT_DRILLS} fault drills, each caught before bad data was published.
        </span>
      </div>
      <div class="fig">
        <span class="n" data-testid="per-run">{cents(s.perRun)}</span>
        <span class="what prose">
          Average compute per daily run. {tense("Costs", "Cost")} about {cents(s.perMonth)} a month.
          <a href="#what-it-covers">What it covers</a>
        </span>
      </div>
    </section>

    <section>
      <h2>Every morning since {longDate(s.first)}</h2>
      <PipelineCalendar months={data.months} counts={s.by} />
      <details>
        <summary>Every day as a table</summary>
        <div class="tablewrap">
          <table data-testid="days">
            <thead>
              <tr><th scope="col">Day</th><th scope="col">State</th><th scope="col">Exported (UTC)</th><th scope="col">Compute</th></tr>
            </thead>
            <tbody>
              {#each [...data.days].reverse() as d (d.day)}
                <tr>
                  <td>{d.day}</td>
                  <td>{stateLabel(d.state)}</td>
                  <td>{d.exportedAt ?? "—"}</td>
                  <td>{d.expected ? cents(d.dollars) : "—"}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  {/if}

  <section>
    <h2>When things went wrong</h2>
    <p class="prose muted lede">
      Incidents, and faults injected into the running system on purpose. Each links to its
      write-up.
    </p>
    <ol class="events" data-testid="events">
      {#each EVENTS as e (e.date + e.text)}
        <li>
          <time datetime={e.date}>{e.date}</time>
          <span class="kind {e.kind}">{KINDS[/** @type {keyof typeof KINDS} */ (e.kind)]}</span>
          <span class="prose">{e.text} <a href={e.href}>Write-up</a></span>
        </li>
      {/each}
    </ol>
    <p class="prose muted also">{ALSO_COVERED.text}</p>
  </section>

  <section>
    <h2>How it works</h2>
    <PipelineDiagram />
  </section>

  <section class="defs">
    <h2>What the figures mean</h2>
    <dl class="prose">
      {#each STATES as st (st.key)}
        <dt>{st.label}</dt>
        <dd>{st.meaning}</dd>
      {/each}
      <dt>On-time share</dt>
      <dd>
        The share of mornings a run was due, and its outcome is recorded, that were exported by 09:00
        UTC. A morning that was held back, late, failed or missed counts against it.
      </dd>
      <dt id="what-it-covers">Compute</dt>
      <dd>
        {COST_COVERS} The average per daily run is the record's total over the mornings a run was
        due, so the day after a quarter's data loads, which costs more, raises it a little. The month
        is the average day's cost over 30 days.
      </dd>
      <dt>Dates and times</dt>
      <dd>
        Every day is a UTC day. The record runs from {s.first ? longDate(s.first) : "its first day"}
        to the day before the site's latest export; a day's state is final once the next morning's
        run has recorded it.
      </dd>
    </dl>
  </section>
</main>

<style>
  .hero { padding: 40px 0 8px; }
  h1 { font-size: clamp(26px, 4vw, 40px); margin: 0 0 10px; letter-spacing: -0.01em; }
  .status { margin: 0; font-size: 16px; color: var(--text); }
  section { padding: 22px 0; }
  h2 { font-size: 18px; font-weight: 600; margin: 0 0 14px; }
  .lede { margin: -6px 0 14px; max-width: 64ch; }

  .figures {
    display: grid; grid-template-columns: repeat(3, 1fr); border-top: 1px solid var(--rule);
    border-bottom: 1px solid var(--rule); padding: 0; margin-top: 18px;
  }
  .fig { padding: 18px 18px 18px 0; border-right: 1px solid var(--rule); display: grid; gap: 6px; align-content: start; }
  .fig + .fig { padding-left: 18px; }
  .fig:last-child { border-right: 0; }
  .n { font-size: 34px; line-height: 1.1; font-variant-numeric: tabular-nums; color: var(--accent); }
  .what { color: var(--muted); font-size: 14px; max-width: 34ch; }
  .what a { white-space: nowrap; }

  details { margin-top: 18px; }
  summary { cursor: pointer; color: var(--accent); font-size: 13px; }
  .tablewrap { max-height: 360px; overflow: auto; margin-top: 10px; border: 1px solid var(--rule); }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { text-align: left; padding: 5px 12px; border-bottom: 1px solid var(--rule); white-space: nowrap; }
  th { position: sticky; top: 0; background: var(--bg); color: var(--muted); font-weight: 500; }

  .events { list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; max-width: 86ch; }
  .events li { display: grid; grid-template-columns: 10ch 13ch 1fr; gap: 12px; align-items: baseline; }
  time { color: var(--muted); font-size: 13px; }
  .kind { font-size: 12px; color: var(--muted); }
  .kind.incident { color: var(--day-held); }
  .kind.drill { color: var(--accent); }
  .also { font-size: 13px; margin: 14px 0 0; max-width: 86ch; }

  .defs dl { display: grid; grid-template-columns: 14ch 1fr; gap: 8px 20px; max-width: 86ch; margin: 0; }
  dt { font-weight: 500; }
  dd { margin: 0; color: var(--muted); }

  @media (max-width: 760px) {
    .figures { grid-template-columns: 1fr; }
    .fig, .fig + .fig { border-right: 0; border-bottom: 1px solid var(--rule); padding: 16px 0; }
    .fig:last-child { border-bottom: 0; }
    .events li { grid-template-columns: 1fr; gap: 2px; }
    .defs dl { grid-template-columns: 1fr; gap: 2px; }
    dd { margin-bottom: 10px; }
  }
</style>
