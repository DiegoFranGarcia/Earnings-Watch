<script>
  // One company's quarters: net income and operating cash flow (after restatements) as lines,
  // and net income as first reported where it was later restated, as open circles, so a
  // restatement shows as a gap between a circle and the line. ECharts loads in the browser only;
  // the page's table holds the same figures without it.
  import { onMount } from "svelte";
  import { money } from "#lib/format.js";

  /**
   * @type {{ quarters: {
   *   end: string, niFirst: number | null, niLatest: number | null,
   *   cashLatest: number | null, niRestated: boolean
   * }[] }}
   */
  let { quarters } = $props();

  /** @type {HTMLDivElement | undefined} */
  let box = $state();
  /** @type {any} */
  let chart = $state.raw(null);
  let theme = $state(0);

  /** @param {string} name */
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

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
        charts.LineChart,
        charts.ScatterChart,
        components.GridComponent,
        components.TooltipComponent,
        components.LegendComponent,
        renderers.CanvasRenderer,
      ]);
      const instance = echarts.init(box);
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

  $effect(() => {
    if (!chart) return;
    void theme;
    const [accent, muted, rule, text, panel] = ["--accent", "--muted", "--rule", "--text", "--panel"].map(css);
    const font = { fontFamily: "IBM Plex Mono", fontSize: 11, color: muted };
    chart.setOption({
      animation: false,
      grid: { left: 64, right: 16, top: 36, bottom: 32 },
      legend: { top: 0, left: 0, textStyle: { ...font, color: text }, itemWidth: 18 },
      tooltip: {
        trigger: "axis",
        backgroundColor: panel,
        borderColor: rule,
        textStyle: { color: text, fontFamily: "IBM Plex Mono", fontSize: 12 },
        valueFormatter: (/** @type {number | null} */ v) => money(v),
      },
      xAxis: {
        type: "category",
        data: quarters.map((q) => q.end),
        axisLabel: font,
        axisLine: { lineStyle: { color: rule } },
      },
      yAxis: {
        type: "value",
        axisLabel: { ...font, formatter: (/** @type {number} */ v) => money(v) },
        splitLine: { lineStyle: { color: rule, opacity: 0.5 } },
      },
      series: [
        {
          name: "Net income",
          type: "line",
          data: quarters.map((q) => q.niLatest),
          lineStyle: { color: accent, width: 2 },
          itemStyle: { color: accent },
          symbolSize: 4,
          connectNulls: false,
        },
        {
          name: "Operating cash flow",
          type: "line",
          data: quarters.map((q) => q.cashLatest),
          lineStyle: { color: muted, width: 2, type: "dashed" },
          itemStyle: { color: muted },
          symbolSize: 4,
          connectNulls: false,
        },
        {
          name: "Net income as first reported",
          type: "scatter",
          data: quarters.map((q) => (q.niRestated ? q.niFirst : null)),
          symbol: "emptyCircle",
          symbolSize: 9,
          itemStyle: { color: text },
        },
      ],
    });
  });
</script>

<div class="canvas" bind:this={box} role="img" aria-label="Line chart of quarterly net income and operating cash flow; the table below holds the same figures."></div>

<style>
  .canvas { height: 320px; border: 1px solid var(--rule); background: var(--panel); padding: 8px 4px 0; }
</style>
