<script>
  // Each company as a dot: the change in net income across, the gap between income and cash up,
  // both as a share of average total assets, so every company can be drawn and the two axes
  // compare. Flagged companies (net income up, operating cash flow not, gap above 10%) sit right
  // of zero and above the dashed line. A company beyond the chart is drawn at its edge as a
  // triangle pointing the way it went, with its real figures in the tooltip. Dragging across the
  // chart selects an area, and the table shows only the companies in it; hovering a row in the
  // table marks its dot. ECharts loads only in the browser, on this page.
  import { onMount } from "svelte";
  import { count, percent } from "#lib/format.js";
  import { CHANGE_RANGE, GAP_RANGE, GAP_THRESHOLD, clamp } from "#lib/screener.js";

  /**
   * @type {{
   *   rows: import("#lib/screener.js").Row[] | null,
   *   selection: { change: number[] | null, gap: number[] | null },
   *   hovered: number | null,
   *   onselect: (s: { change: number[], gap: number[] } | null) => void,
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

  const plotted = $derived((rows ?? []).filter((r) => r.change != null && r.gap != null));
  const beyond = $derived(
    plotted.filter((r) => clamp(/** @type {number} */ (r.change), CHANGE_RANGE) !== r.change || clamp(/** @type {number} */ (r.gap), GAP_RANGE) !== r.gap).length,
  );
  const indexOf = $derived(new Map(plotted.map((r, i) => [r.cik, i])));

  /** @param {string} name */
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  /** @param {string} text */
  const escape = (text) => text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  /** @param {number} v */
  const pct = (v) => `${Math.round(v * 100)}%`;

  /**
   * A dot, or for a company beyond the chart a triangle at the edge pointing the way it went.
   * @param {import("#lib/screener.js").Row} r
   * @param {number} i
   */
  function point(r, i) {
    const x = /** @type {number} */ (r.change);
    const y = /** @type {number} */ (r.gap);
    const value = [clamp(x, CHANGE_RANGE), clamp(y, GAP_RANGE), i];
    if (value[0] === x && value[1] === y) return value;
    const rotate = y > GAP_RANGE[1] ? 0 : y < GAP_RANGE[0] ? 180 : x > CHANGE_RANGE[1] ? -90 : 90;
    return { value, symbol: "triangle", symbolSize: 9, symbolRotate: rotate };
  }

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
        const [change, gap] = area.coordRange;
        onselect({ change: [...change], gap: [...gap] });
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
    const [accent, muted, rule, text, panel] = ["--accent", "--muted", "--rule", "--text", "--panel"].map(css);
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
      xAxis: { ...axis, min: CHANGE_RANGE[0], max: CHANGE_RANGE[1], name: "Change in net income / assets", nameGap: 28, interval: 0.25 },
      yAxis: { ...axis, min: GAP_RANGE[0], max: GAP_RANGE[1], name: "Gap / assets", nameGap: 44, interval: 0.25 },
      tooltip: {
        trigger: "item",
        backgroundColor: panel,
        borderColor: rule,
        textStyle: { color: text, fontFamily: "IBM Plex Mono", fontSize: 12 },
        formatter: (/** @type {any} */ p) => {
          const i = Array.isArray(p.data) ? p.data[2] : p.data.value[2];
          const r = plotted[i];
          if (!r) return "";
          const edge = Array.isArray(p.data) ? "" : "<br>Beyond the chart: drawn at its edge";
          const check = r.implausible ? "<br>Check the filing: figures above twice assets" : "";
          return `${escape(r.name)}${r.flagged ? " (flagged)" : ""}<br>Income change ${percent(r.change)} of assets, gap ${percent(r.gap)}${edge}${check}`;
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
          data: plotted.map(point),
          itemStyle: {
            color: (/** @type {any} */ p) => {
              const i = Array.isArray(p.data) ? p.data[2] : p.data.value[2];
              return plotted[i]?.flagged ? accent : muted;
            },
            opacity: 0.85,
          },
          emphasis: { scale: 2.4, itemStyle: { borderColor: text, borderWidth: 1.5, opacity: 1 } },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: accent, type: "dashed", width: 1 },
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
    const { change, gap } = selection;
    const areas =
      change || gap
        ? [{ brushType: "rect", xAxisIndex: 0, yAxisIndex: 0, coordRange: [change ?? CHANGE_RANGE, gap ?? GAP_RANGE] }]
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
  <div class="canvas" bind:this={box} role="img" aria-label="Scatter chart of the companies below: change in net income across, gap between income and cash up, both as a share of assets. Drag across it to select an area."></div>
  <figcaption class="prose muted">
    {#if rows}
      All {count(plotted.length)} companies, both figures as a share of their assets. Flagged
      companies, in the accent color, sit right of zero (net income up) and above the dashed
      10% line, with operating cash flow not up. {#if beyond}{count(beyond)} beyond the chart are
      drawn at its edge as triangles; hover for their figures.{/if} Drag across the chart to keep
      only the companies in an area; click it to clear.
    {:else}
      Loading the chart.
    {/if}
  </figcaption>
</figure>

<style>
  .scatter { margin: 0 0 18px; }
  .canvas { height: 360px; border: 1px solid var(--rule); background: var(--panel); }
  figcaption { font-size: 13px; margin-top: 6px; max-width: 80ch; }
</style>
