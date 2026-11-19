<script>
  /** @type {{ values: number[], label: string }} */
  let { values, label } = $props();
  const W = 84, H = 20;
  const points = $derived.by(() => {
    if (values.length < 2) return "";
    const max = Math.max(...values), min = Math.min(...values), span = max - min || 1;
    return values
      .map((v, i) => `${((i * W) / (values.length - 1)).toFixed(1)},${(H - 2 - ((v - min) / span) * (H - 4)).toFixed(1)}`)
      .join(" ");
  });
</script>

{#if points}
  <svg viewBox="0 0 {W} {H}" width={W} height={H} role="img" aria-label={label}>
    <polyline fill="none" stroke="var(--accent)" stroke-width="1.5" points={points} />
  </svg>
{/if}

<style>
  svg { vertical-align: middle; }
</style>
