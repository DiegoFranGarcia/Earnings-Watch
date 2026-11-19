<script>
  // Each company as a dot: net income growth across, the gap between income and cash (as a
  // share of assets) up. Flagged companies sit right of zero growth and above the threshold.
  // Dragging across the chart selects an area, and the table shows only the companies in it;
  // hovering a row in the table marks its dot. ECharts loads only in the browser, on this page.
  import { onMount } from "svelte";
  import { count, percent } from "#lib/format.js";
  import { GAP_RANGE, GAP_THRESHOLD, GROWTH_RANGE, clamp } from "#lib/screener.js";

  /**
   * @type {{
   *   rows: import("#lib/screener.js").Row[] | null,
   *   selection: { growth: number[] | null, gap: number[] | null },
   *   hovered: number | null,
   *   onselect: (s: { growth: number[], gap: number[] } | null) => void,
   * }}
   */
  let { rows, selection, hovered, onselect } = $props();

  /** @type {HTMLDivElement | undefined} */
  let box = $state();
  /** @type {any} */
  let chart = $state.raw(null);
  let theme = $state(0);
  /** Drawn with every row: the browser tests wait for this before dragging. */
  let drawn = $state(false);

  const plotted = $derived((rows ?? []).filter((r) => r.growth != null && r.gap != null));
  const unplotted = $derived((rows?.length ?? 0) - plotted.length);
  const indexOf = $derived(new Map(plotted.map((r, i) => [r.cik, i])));

  /** @param {string} name */
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  /** @param {string} text */
  const escape = (text) =>
    text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  /** @param {number} v */
  const pct = (v) => `${Math.round(v * 100)}%`;

  onMount(() => {
    let disposed = false;
    /** @type {ResizeObserver | undefined} */
    let resize;
    /** @type {MutationObserver | undefined} */
    let themes;
    (async () => {
      const [echarts, charts, components, renderers] = await Promise.all([
        import("echarts/core"),
        import("echarts/charts"),
        import("echarts/components"),
        import("echarts/renderers"),
      ]);
      if (disposed || !box) return;
      echarts.use([
        charts.ScatterChart,
        components.GridComponent,
        components.TooltipComponent,
        components.BrushComponent,
        components.MarkLineComponent,
        renderers.CanvasRenderer,
      ]);
      const instance = echarts.init(box);
      instance.on("brushEnd", (/** @type {any} */ e) => {
        const area = e.areas?.[0];
        if (!area) return onselect(null);
        const [growth, gap] = area.coordRange;
        onselect({ growth: [...growth], gap: [...gap] });
      });
      resize = new ResizeObserver(() => instance.resize());
      resize.observe(box);
      themes = new MutationObserver(() => theme++);
      themes.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      chart = instance;
    })();
    return () => {
      disposed = true;
      resize?.disconnect();
      themes?.disconnect();
      chart?.dispose();
    };
  });

  // Draw, and redraw on a new theme, new rows or a new selection; the selected area is drawn
  // from the page's state, so one chosen elsewhere (the address, "Clear filters") shows too.
  $effect(() => {
    if (!chart) return;
    void theme;
    const [accent, muted, rule, text, panel, down] = ["--accent", "--muted", "--rule", "--text", "--panel", "--down"].map(css);
    const axis = {
      type: "value",
      nameLocation: "middle",
      nameTextStyle: { color: muted, fontFamily: "IBM Plex Mono", fontSize: 12 },
      axisLabel: { color: muted, fontFamily: "IBM Plex Mono", fontSize: 11, formatter: pct },
      axisLine: { lineStyle: { color: rule } },
      splitLine: { lineStyle: { color: rule, opacity: 0.5 } },
    };
    chart.setOption({
      animation: false,
      grid: { left: 60, right: 16, top: 16, bottom: 44 },
      xAxis: { ...axis, min: GROWTH_RANGE[0], max: GROWTH_RANGE[1], name: "Net income growth on a year ago", nameGap: 28, interval: 1 },
      yAxis: { ...axis, min: GAP_RANGE[0], max: GAP_RANGE[1], name: "Gap / assets", nameGap: 44, interval: 0.1 },
      tooltip: {
        trigger: "item",
        backgroundColor: panel,
        borderColor: rule,
        textStyle: { color: text, fontFamily: "IBM Plex Mono", fontSize: 12 },
        formatter: (/** @type {any} */ p) => {
          const r = plotted[p.data[2]];
          if (!r) return "";
          const edge = r.growth !== p.data[0] || r.gap !== p.data[1] ? "<br>Beyond the chart: drawn at its edge" : "";
          return `${escape(r.name)}${r.flagged ? " (flagged)" : ""}<br>Growth ${percent(r.growth, 0)}, gap ${percent(r.gap)}${edge}`;
        },
      },
      brush: {
        xAxisIndex: 0,
        yAxisIndex: 0,
        brushType: "rect",
        brushMode: "single",
        throttleType: "debounce",
        throttleDelay: 150,
        brushStyle: { borderWidth: 1, color: "rgba(127, 127, 127, 0.12)", borderColor: accent },
        outOfBrush: { colorAlpha: 0.2 },
      },
      series: [
        {
          type: "scatter",
          symbolSize: 6,
          data: plotted.map((r, i) => [
            clamp(/** @type {number} */ (r.growth), GROWTH_RANGE),
            clamp(/** @type {number} */ (r.gap), GAP_RANGE),
            i,
          ]),
          itemStyle: {
            color: (/** @type {any} */ p) => (plotted[p.data[2]]?.flagged ? accent : muted),
            opacity: 0.85,
          },
          emphasis: { scale: 2.4, itemStyle: { borderColor: text, borderWidth: 1.5, opacity: 1 } },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: down, type: "dashed", width: 1 },
            label: { color: muted, fontFamily: "IBM Plex Mono", fontSize: 11 },
            data: [
              { yAxis: GAP_THRESHOLD, label: { formatter: "flag threshold", position: "insideEndTop" } },
              { xAxis: 0, label: { formatter: "" } },
            ],
          },
        },
      ],
    });
    chart.dispatchAction({ type: "takeGlobalCursor", key: "brush", brushOption: { brushType: "rect", brushMode: "single" } });
    const { growth, gap } = selection;
    const areas =
      growth || gap
        ? [{ brushType: "rect", xAxisIndex: 0, yAxisIndex: 0, coordRange: [growth ?? GROWTH_RANGE, gap ?? GAP_RANGE] }]
        : [];
    chart.dispatchAction({ type: "brush", areas });
    drawn = rows != null;
  });

  // The company under the pointer in the table, marked on the chart.
  $effect(() => {
    if (!chart) return;
    chart.dispatchAction({ type: "downplay", seriesIndex: 0 });
    const i = hovered == null ? undefined : indexOf.get(hovered);
    if (i != null) chart.dispatchAction({ type: "highlight", seriesIndex: 0, dataIndex: i });
  });
</script>

<figure class="scatter" data-chart={drawn ? "ready" : "loading"}>
  <div class="canvas" bind:this={box} role="img" aria-label="Scatter chart of the companies below: net income growth across, gap between income and cash as a share of assets up. Drag across it to select an area."></div>
  <figcaption class="prose muted">
    {#if rows}
      {count(plotted.length)} companies drawn; flagged ones in the accent color, above the dashed
      threshold. Drag across the chart to keep only the companies in an area; click it to clear.
      {#if unplotted}{count(unplotted)} without a positive income a year ago have no growth figure and aren't drawn.{/if}
    {:else}
      Loading the chart.
    {/if}
  </figcaption>
</figure>

<style>
  .scatter { margin: 0 0 18px; }
  .canvas { height: 340px; border: 1px solid var(--rule); background: var(--panel); }
  figcaption { font-size: 13px; margin-top: 6px; max-width: 80ch; }
</style>
