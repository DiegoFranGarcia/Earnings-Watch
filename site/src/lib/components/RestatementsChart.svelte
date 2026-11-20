<script>
  // Companies that changed a figure they had already reported, each year, stacked by the first
  // kind of change: as a share of the companies reporting the figure that year (so XBRL's
  // phase-in does not read as a trend), or as a count. The phase-in years are shaded, and the
  // year still under way is drawn lighter. Clicking a year filters the table below.
  import { onMount } from "svelte";
  import { count, percent } from "#lib/format.js";
  import { KINDS, PHASE_IN, barValue } from "#lib/restatements.js";

  /**
   * @type {{
   *   years: import("#lib/restatements.js").Year[], tags: boolean, counts: boolean,
   *   label: string, selected: number | null, current: number,
   *   onselect: (year: number | null) => void,
   * }}
   */
  let { years, tags, counts, label, selected, current, onselect } = $props();

  /** @type {HTMLDivElement | undefined} */
  let box = $state();
  /** @type {any} */
  let chart = $state.raw(null);
  let theme = $state(0);
  /** Drawn: the browser tests wait for this before clicking. */
  let drawn = $state(false);

  const kinds = $derived(KINDS.filter(([kind]) => tags || kind !== "tag_switch"));

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
        charts.BarChart,
        components.GridComponent,
        components.TooltipComponent,
        components.LegendComponent,
        components.MarkAreaComponent,
        renderers.CanvasRenderer,
      ]);
      const instance = echarts.init(box);
      // A click anywhere in a year's column picks that year (bars can be too thin to hit).
      instance.getZr().on("click", (/** @type {any} */ e) => {
        const point = [e.offsetX, e.offsetY];
        if (!instance.containPixel("grid", point)) return;
        const [i] = instance.convertFromPixel({ seriesIndex: 0 }, point);
        const year = years[Math.round(i)]?.year;
        if (year != null) onselect(year === selected ? null : year);
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

  $effect(() => {
    if (!chart) return;
    void theme;
    const [accent, muted, rule, text, panel, band] = ["--accent", "--muted", "--rule", "--text", "--panel", "--band"].map(css);
    const colors = { correction: accent, recast: muted, tag_switch: rule };
    const font = { fontFamily: "IBM Plex Mono", fontSize: 11, color: muted };
    /** @param {number | null} v */
    const show = (v) => (v == null ? "—" : counts ? count(v) : percent(v));
    chart.setOption(
      {
        animation: false,
        grid: { left: 56, right: 16, top: 60, bottom: 28 },
        legend: { top: 0, left: 0, textStyle: { ...font, color: text }, itemWidth: 14, selectedMode: false },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          backgroundColor: panel,
          borderColor: rule,
          textStyle: { color: text, fontFamily: "IBM Plex Mono", fontSize: 12 },
          valueFormatter: show,
        },
        xAxis: {
          type: "category",
          data: years.map((y) => String(y.year)),
          axisLabel: font,
          axisLine: { lineStyle: { color: rule } },
        },
        yAxis: {
          type: "value",
          name: label,
          nameTextStyle: { ...font, align: "left" },
          axisLabel: { ...font, formatter: (/** @type {number} */ v) => (counts ? count(v) : `${Math.round(v * 100)}%`) },
          splitLine: { lineStyle: { color: rule, opacity: 0.5 } },
        },
        series: kinds.map(([kind, name], i) => ({
          name,
          type: "bar",
          stack: "kinds",
          // The series' colour too, so the legend's swatches match the bars.
          itemStyle: { color: colors[/** @type {keyof typeof colors} */ (kind)] },
          barMaxWidth: 28,
          data: years.map((y) => ({
            value: barValue(y, kind, counts),
            itemStyle: {
              color: colors[/** @type {keyof typeof colors} */ (kind)],
              opacity: y.year === current ? 0.45 : selected == null || selected === y.year ? 1 : 0.35,
            },
          })),
          ...(i === 0
            ? {
                markArea: {
                  silent: true,
                  itemStyle: { color: band, opacity: 0.6 },
                  label: { ...font, position: "insideTop", formatter: "XBRL phase-in" },
                  data: [[{ xAxis: String(PHASE_IN[0]) }, { xAxis: String(PHASE_IN[1]) }]],
                },
              }
            : {}),
        })),
      },
      { notMerge: true },
    );
    drawn = true;
  });
</script>

<figure class="chart" data-chart={drawn ? "ready" : "loading"}>
  <div class="canvas" bind:this={box} role="img" aria-label="Bar chart of companies that changed a figure they had already reported, each year, by kind of change; the table of years below holds the same figures."></div>
</figure>

<style>
  .chart { margin: 0 0 8px; }
  .canvas { height: 340px; border: 1px solid var(--rule); background: var(--panel); padding: 8px 4px 0; cursor: pointer; }
</style>
