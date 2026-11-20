<script>
  // The share of filings in by the deadline, each period year, a line per filer group. Drawn
  // as SVG when the site is built, so it reads without JavaScript; in the browser it is redrawn
  // at the width it has. Years whose filings are not all due yet are dashed and shaded, and so
  // are the years XBRL tagging phased in.
  import { count, percent } from "#lib/format.js";
  import { PHASE_IN } from "#lib/timeliness.js";

  /**
   * @type {{
   *   lines: ReturnType<typeof import("#lib/timeliness.js").series>,
   *   complete: number, form: string,
   * }}
   */
  let { lines, complete, form } = $props();

  let width = $state(720);
  const height = 300;
  const COLORS = /** @type {Record<string, string>} */ ({
    large_accelerated: "var(--text)",
    accelerated: "var(--accent-dim)",
    non_accelerated: "var(--accent)",
  });

  const wide = $derived(width >= 560);
  const m = $derived({ top: 26, right: wide ? 168 : 14, bottom: 28, left: 44 });
  const years = $derived([...new Set(lines.flatMap((l) => l.points.map((p) => p.year)))].sort((a, b) => a - b));
  const shares = $derived(lines.flatMap((l) => l.points.map((p) => p.share)).filter((v) => v != null));
  /** The bottom of the scale: a round tenth below the lowest share. */
  const low = $derived(Math.max(0, Math.floor((Math.min(1, ...shares) - 0.02) * 10) / 10));
  const step = $derived(1 - low > 0.5 ? 0.2 : 0.1);
  const ticks = $derived(
    Array.from({ length: Math.round((1 - low) / step) + 1 }, (_, i) => Math.round((low + i * step) * 100) / 100),
  );

  /** @param {number} year */
  const x = (year) =>
    m.left + (years.length < 2 ? 0 : ((year - years[0]) / (years[years.length - 1] - years[0])) * (width - m.left - m.right));
  /** @param {number} v */
  const y = (v) => m.top + ((1 - v) / (1 - low)) * (height - m.top - m.bottom);
  const slot = $derived(years.length < 2 ? 0 : (width - m.left - m.right) / (years.length - 1));

  /** @param {{ year: number, share: number | null }[]} points */
  const path = (points) =>
    points
      .filter((p) => p.share != null)
      .map((p, i) => `${i ? "L" : "M"}${x(p.year).toFixed(1)},${y(/** @type {number} */ (p.share)).toFixed(1)}`)
      .join("");

  const drawn = $derived(
    lines.map((l) => {
      const done = l.points.filter((p) => p.year <= complete);
      const open = l.points.filter((p) => p.year > complete);
      const last = done[done.length - 1];
      return { ...l, solid: path(done), dashed: open.length && last ? path([last, ...open]) : "", last };
    }),
  );

  /** Labels at the end of each line, pushed apart so they never overlap. */
  const labels = $derived.by(() => {
    const placed = drawn
      .filter((l) => l.last?.share != null)
      .map((l) => ({ group: l.group, label: l.label, share: /** @type {number} */ (l.last?.share), at: y(/** @type {number} */ (l.last?.share)) }))
      .sort((a, b) => a.at - b.at);
    for (let i = 1; i < placed.length; i++) placed[i].at = Math.max(placed[i].at, placed[i - 1].at + 16);
    return placed;
  });

  const lastYear = $derived(years[years.length - 1]);
  /** Every second year (fourth on a phone), and the last, never crowding it. */
  const showYear = (/** @type {number} */ year) =>
    year === lastYear || ((year - years[0]) % (wide ? 2 : 4) === 0 && lastYear - year >= (wide ? 2 : 3));
</script>

{#if !wide}
  <p class="key" aria-hidden="true">
    {#each lines as l (l.group)}<span><i style:background={COLORS[l.group]}></i>{l.label}</span>{/each}
  </p>
{/if}
<div class="chart" bind:clientWidth={width}>
  <svg
    viewBox="0 0 {width} {height}"
    role="img"
    aria-label="Line chart of the share of {form} filings made by the deadline, each period year, for each filer group; the table of years below holds the same figures."
  >
    {#if years.length}
      {#if years[0] <= PHASE_IN[1]}
        <rect class="band" x={m.left} y={m.top} width={Math.max(0, x(PHASE_IN[1]) + slot / 2 - m.left)} height={height - m.top - m.bottom} />
        <text class="note" x={m.left + 4} y={m.top - 8}>XBRL phase-in</text>
      {/if}
      {#if lastYear > complete}
        <rect class="band" x={x(complete) + slot / 2} y={m.top} width={Math.max(0, width - m.right - x(complete) - slot / 2)} height={height - m.top - m.bottom} />
        <text class="note" x={width - m.right} y={m.top - 8} text-anchor="end">Not all due yet</text>
      {/if}
    {/if}
    {#each ticks as t (t)}
      <line class="grid" x1={m.left} x2={width - m.right} y1={y(t)} y2={y(t)} />
      <text class="axis" x={m.left - 6} y={y(t) + 4} text-anchor="end">{Math.round(t * 100)}%</text>
    {/each}
    {#each years as year (year)}
      {#if showYear(year)}
        <text class="axis" x={x(year)} y={height - 8} text-anchor="middle">{year}</text>
      {/if}
    {/each}
    {#each drawn as l (l.group)}
      <path class="line" d={l.solid} stroke={COLORS[l.group]} data-group={l.group} />
      {#if l.dashed}<path class="line open" d={l.dashed} stroke={COLORS[l.group]} />{/if}
      {#each l.points as p (p.year)}
        {#if p.share != null}
          <circle cx={x(p.year)} cy={y(p.share)} r="2.5" fill={COLORS[l.group]} opacity={p.year > complete ? 0.5 : 1}>
            <title>{l.label}, {p.year}{p.year > complete ? " (to date)" : ""}: {percent(p.share)} of {count(p.filings)} on time</title>
          </circle>
        {/if}
      {/each}
    {/each}
    {#if wide}
      {#each labels as l (l.group)}
        <text class="label" x={width - m.right + 10} y={l.at + 4} fill={COLORS[l.group]}>{l.label} {percent(l.share, 0)}</text>
      {/each}
    {/if}
  </svg>
</div>

<style>
  .chart { border: 1px solid var(--rule); background: var(--panel); }
  svg { display: block; width: 100%; height: auto; font-family: "IBM Plex Mono", monospace; }
  .band { fill: var(--band); opacity: 0.8; }
  :global(:root[data-theme="dark"]) .band { fill: var(--rule); opacity: 0.35; }
  .grid { stroke: var(--rule); stroke-opacity: 0.6; }
  .axis, .note { fill: var(--muted); font-size: 11px; }
  .label { font-size: 12px; font-weight: 500; }
  .line { fill: none; stroke-width: 2; }
  .open { stroke-dasharray: 4 4; opacity: 0.7; }
  .key { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px; margin: 0 0 6px; }
  .key i { display: inline-block; width: 12px; height: 3px; margin-right: 6px; vertical-align: middle; }
</style>
