<script>
  // How it works: the steps in order, Airflow as the band above them that starts each one, and
  // the check that decides whether this site changes. Drawn left to right on a wide screen and top
  // to bottom on a narrow one (two SVGs, one shown); colours follow the theme.

  /** The steps, in order. @type {{ name: string, lines: string[], kind?: "gate" | "live" }[]} */
  const STEPS = [
    { name: "SEC EDGAR", lines: ["daily filing index,", "quarterly data sets"] },
    { name: "S3, bronze", lines: ["each file as the", "SEC published it"] },
    { name: "S3, silver", lines: ["Parquet: Spark (EMR)", "or Python (daily)"] },
    { name: "Snowflake", lines: ["loaded into RAW,", "idempotently"] },
    { name: "dbt", lines: ["volume checks, then", "models and tests"] },
    { name: "Every check passes?", lines: ["no: the site keeps", "its last good data"], kind: "gate" },
    { name: "This site", lines: ["exported as Parquet,", "built on GitHub Pages"], kind: "live" },
  ];
  const BAND = [
    "Airflow 3 on one EC2 host starts each step when the one before it lands its data: the daily index at 06:00 UTC,",
    "the quarterly data sets on each quarter's first day. A failed task retries, then alerts on Discord.",
  ];
  const AUDIT = "AUDIT, in Snowflake: every task try, test result, volume check and cost. This page is built from it.";

  // The wide drawing.
  const W = { box: 136, gap: 22, top: 112, h: 92, left: 18 };
  const x = (/** @type {number} */ i) => W.left + i * (W.box + W.gap);
  const width = x(STEPS.length) - W.gap + W.left;

  // The narrow drawing.
  const N = { top: 120, h: 66, gap: 28, left: 46, w: 296 };
  const y = (/** @type {number} */ i) => N.top + i * (N.h + N.gap);
  const height = y(STEPS.length) + 70;
</script>

<figure class="diagram" aria-labelledby="diagram-caption">
  <figcaption id="diagram-caption" class="visually-hidden">
    The pipeline, in order: {STEPS.map((s) => `${s.name} (${s.lines.join(" ")})`).join(", then ")}.
    {BAND.join(" ")} {AUDIT}
  </figcaption>

  <svg class="wide" viewBox="0 0 {width} 330" aria-hidden="true" focusable="false">
    <defs>
      <marker id="arrow-w" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
        <path d="M0,0 L8,4 L0,8 z" class="head" />
      </marker>
    </defs>
    <rect class="band" x={W.left} y="16" width={width - 2 * W.left} height="58" />
    <text class="band-t" x={W.left + 14} y="40">{BAND[0]}</text>
    <text class="band-t" x={W.left + 14} y="60">{BAND[1]}</text>
    {#each STEPS as s, i (s.name)}
      <line class="tick" x1={x(i) + W.box / 2} y1="74" x2={x(i) + W.box / 2} y2={W.top} />
      <rect class="box {s.kind ?? ''}" x={x(i)} y={W.top} width={W.box} height={W.h} />
      <text class="name {s.kind ?? ''}" x={x(i) + 12} y={W.top + 28}>{s.name === "Every check passes?" ? "Every check" : s.name}</text>
      {#if s.name === "Every check passes?"}<text class="name gate" x={x(i) + 12} y={W.top + 45}>passes?</text>{/if}
      {#each s.lines as line, j (j)}
        <text class="sub" x={x(i) + 12} y={W.top + (s.kind === "gate" ? 64 : 50) + j * 16}>{line}</text>
      {/each}
      {#if i < STEPS.length - 1}
        <line class="flow" x1={x(i) + W.box + 2} y1={W.top + W.h / 2} x2={x(i + 1) - 3} y2={W.top + W.h / 2} marker-end="url(#arrow-w)" />
      {/if}
    {/each}
    <rect class="audit" x={x(3)} y="252" width={x(6) + W.box - x(3)} height="44" />
    <text class="sub strong" x={x(3) + 12} y="279">{AUDIT}</text>
    <line class="flow" x1={x(4) + W.box / 2} y1={W.top + W.h + 2} x2={x(4) + W.box / 2} y2="249" marker-end="url(#arrow-w)" />
    <line class="flow" x1={x(6) + W.box / 2} y1="252" x2={x(6) + W.box / 2} y2={W.top + W.h + 3} marker-end="url(#arrow-w)" />
  </svg>

  <svg class="narrow" viewBox="0 0 360 {height}" aria-hidden="true" focusable="false">
    <defs>
      <marker id="arrow-n" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
        <path d="M0,0 L8,4 L0,8 z" class="head" />
      </marker>
    </defs>
    <rect class="band" x="10" y="10" width="340" height="88" />
    <text class="band-t" x="22" y="32">Airflow 3, on one EC2 host, starts</text>
    <text class="band-t" x="22" y="50">each step when the one before lands</text>
    <text class="band-t" x="22" y="68">its data. Failed tasks retry, then</text>
    <text class="band-t" x="22" y="86">alert on Discord.</text>
    <line class="tick" x1="26" y1="98" x2="26" y2={y(STEPS.length - 1) + N.h / 2} />
    {#each STEPS as s, i (s.name)}
      <line class="tick" x1="26" y1={y(i) + N.h / 2} x2={N.left} y2={y(i) + N.h / 2} />
      <rect class="box {s.kind ?? ''}" x={N.left} y={y(i)} width={N.w} height={N.h} />
      <text class="name {s.kind ?? ''}" x={N.left + 12} y={y(i) + 24}>{s.name}</text>
      <text class="sub" x={N.left + 12} y={y(i) + 46}>{s.lines.join(" ")}</text>
      {#if i < STEPS.length - 1}
        <line class="flow" x1={N.left + N.w / 2} y1={y(i) + N.h + 2} x2={N.left + N.w / 2} y2={y(i + 1) - 3} marker-end="url(#arrow-n)" />
      {/if}
    {/each}
    <rect class="audit" x="10" y={y(STEPS.length) - 8} width="340" height="62" />
    <text class="sub strong" x="22" y={y(STEPS.length) + 16}>AUDIT, in Snowflake: every task try,</text>
    <text class="sub strong" x="22" y={y(STEPS.length) + 36}>test, volume check and cost. This page.</text>
  </svg>
</figure>

<style>
  .diagram { margin: 0; }
  svg { display: block; width: 100%; height: auto; }
  .narrow { display: none; max-width: 420px; }
  @media (max-width: 860px) {
    .wide { display: none; }
    .narrow { display: block; }
  }
  .band { fill: var(--band); stroke: var(--rule); }
  :global([data-theme="dark"]) .band { fill: var(--panel); }
  .band-t { fill: var(--text); font: 13px "IBM Plex Sans", system-ui, sans-serif; }
  .box { fill: var(--panel); stroke: var(--rule); }
  .box.gate { fill: none; stroke: var(--accent); stroke-dasharray: 5 4; }
  .box.live { stroke: var(--accent-dim); }
  .name { fill: var(--text); font: 500 14px "IBM Plex Mono", ui-monospace, monospace; }
  .name.gate, .name.live { fill: var(--accent); }
  .sub { fill: var(--muted); font: 12px "IBM Plex Sans", system-ui, sans-serif; }
  .sub.strong { fill: var(--text); }
  .audit { fill: none; stroke: var(--rule); stroke-dasharray: 2 3; }
  .tick { stroke: var(--rule); stroke-dasharray: 2 3; }
  .flow { stroke: var(--accent); stroke-width: 1.5; }
  .head { fill: var(--accent); }
</style>
