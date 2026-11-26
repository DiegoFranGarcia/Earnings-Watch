<script>
  // Every day of the pipeline's record, one cell each, a block per month: a column per week,
  // Monday at the top. Pointing at a cell, tapping it or moving to it with the arrow keys shows
  // that day below the calendar; without JavaScript each cell still names its day and state.
  import { STATES, longDate, stateLabel } from "#lib/pipeline.js";

  /**
   * @type {{
   *   months: ReturnType<typeof import("#lib/pipeline.js").months>,
   *   counts: Record<string, number>,
   * }}
   */
  let { months, counts } = $props();

  /** Every day of the record, in order: what the arrow keys move through. */
  const days = $derived(months.flatMap((m) => m.cells.filter((c) => c.day).map((c) => c.iso)));
  let selected = $state(/** @type {string | null} */ (null));
  const current = $derived(selected ?? days[days.length - 1] ?? null);
  const shown = $derived(
    months.flatMap((m) => m.cells).find((c) => c.iso === current)?.day ?? null,
  );

  const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

  /** @param {{ day: import("#lib/pipeline.js").Day }} cell @param {number} row */
  function describe(cell, row) {
    const d = cell.day;
    const when = d.exportedAt ? `, exported ${d.exportedAt} UTC` : "";
    return `${WEEKDAYS[row]}, ${longDate(d.day)}: ${stateLabel(d.state)}${when}`;
  }

  /** @param {KeyboardEvent} event */
  function move(event) {
    const steps = { ArrowDown: 1, ArrowUp: -1, ArrowRight: 7, ArrowLeft: -7 };
    const at = days.indexOf(current ?? "");
    let next = at;
    if (event.key in steps) next = at + steps[/** @type {keyof typeof steps} */ (event.key)];
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = days.length - 1;
    else return;
    event.preventDefault();
    next = Math.max(0, Math.min(days.length - 1, next));
    selected = days[next];
    /** @type {HTMLElement | null} */ (
      document.querySelector(`[data-day="${days[next]}"]`)
    )?.focus();
  }
</script>

<div class="calendar">
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="months" onkeydown={move} data-testid="calendar">
    {#each months as m (m.key)}
      <figure class="month">
        <figcaption>{m.label}</figcaption>
        <div class="grid" style="--weeks: {m.weeks}">
          {#each m.cells as cell (cell.iso)}
            {#if cell.day}
              <button
                type="button"
                class="cell s-{cell.day.state}"
                class:on={cell.iso === current}
                style="grid-row: {cell.row + 1}; grid-column: {cell.col + 1}"
                data-day={cell.iso}
                data-state={cell.day.state}
                title={describe(/** @type {any} */ (cell), cell.row)}
                aria-label={describe(/** @type {any} */ (cell), cell.row)}
                tabindex={cell.iso === current ? 0 : -1}
                onmouseenter={() => (selected = cell.iso)}
                onfocus={() => (selected = cell.iso)}
                onclick={() => (selected = cell.iso)}
              ></button>
            {:else}
              <span class="cell out" style="grid-row: {cell.row + 1}; grid-column: {cell.col + 1}" aria-hidden="true"></span>
            {/if}
          {/each}
        </div>
      </figure>
    {/each}
  </div>

  <p class="detail" aria-live="polite" data-testid="day-detail">
    {#if shown}
      <span class="swatch s-{shown.state}" aria-hidden="true"></span>
      <span>{longDate(shown.day)}: <b>{stateLabel(shown.state)}</b>{#if shown.exportedAt}, exported {shown.exportedAt} UTC{/if}.</span>
    {/if}
  </p>

  <ul class="legend" aria-label="What the colours mean">
    {#each STATES as s (s.key)}
      {#if s.key !== "not_recorded" || counts[s.key]}
        <li>
          <span class="swatch s-{s.key}" aria-hidden="true"></span>{s.label}
          <span class="n">{counts[s.key] ?? 0}</span>
        </li>
      {/if}
    {/each}
  </ul>
  <p class="how prose muted">Each column is a week, Monday at the top.</p>
</div>

<style>
  .months { display: flex; flex-wrap: wrap; gap: 20px 28px; }
  .month { margin: 0; }
  figcaption { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
  .grid {
    display: grid; gap: 3px;
    grid-template-rows: repeat(7, var(--cell));
    grid-template-columns: repeat(var(--weeks), var(--cell));
  }
  .calendar { --cell: 19px; }

  .cell, .swatch {
    display: block; width: var(--cell); height: var(--cell); padding: 0; margin: 0;
    border: 0; background: none; font: inherit;
  }
  button.cell { cursor: pointer; }
  button.cell:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .cell.on { box-shadow: 0 0 0 1px var(--bg), 0 0 0 3px var(--text); }

  /* Each state differs in shape or texture as well as colour. */
  .s-met { background: var(--accent); }
  .s-late { background: var(--accent-dim); }
  .s-held { background: var(--day-held); }
  .s-failed {
    background: repeating-linear-gradient(135deg, var(--text) 0 2px, transparent 2px 4px);
    box-shadow: inset 0 0 0 1px var(--text);
  }
  .s-missed { box-shadow: inset 0 0 0 2px var(--text); }
  .s-no_run_expected { background: var(--day-none); }
  .s-not_recorded { box-shadow: inset 0 0 0 1px var(--muted); background: transparent; opacity: 0.8; }
  .cell.on.s-failed { box-shadow: inset 0 0 0 1px var(--text), 0 0 0 1px var(--bg), 0 0 0 3px var(--text); }
  .cell.on.s-missed { box-shadow: inset 0 0 0 2px var(--text), 0 0 0 1px var(--bg), 0 0 0 3px var(--text); }
  .cell.on.s-not_recorded { box-shadow: inset 0 0 0 1px var(--muted), 0 0 0 1px var(--bg), 0 0 0 3px var(--text); }

  .detail {
    min-height: 1.5em; margin: 16px 0 12px; display: flex; gap: 10px; align-items: center;
    font-size: 14px;
  }
  .detail .swatch { flex: none; }
  .legend {
    list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 8px 22px;
    font-size: 13px;
  }
  .legend li { display: flex; align-items: center; gap: 8px; }
  .legend .n { color: var(--muted); font-variant-numeric: tabular-nums; }
  .how { font-size: 13px; margin: 10px 0 0; }

  @media (max-width: 760px) {
    .calendar { --cell: 16px; }
    .months { gap: 18px 22px; }
  }
</style>
