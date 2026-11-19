<script>
  import { day, utcTime } from "#lib/format.js";
  import { link } from "#lib/pages.js";

  /** @type {{ status: { exported_at: string, through: string, newest: string } }} */
  let { status } = $props();
  let theme = $state("light");

  $effect(() => {
    theme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  });

  function toggle() {
    theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("ew-theme", theme);
    } catch {
      // Storage blocked: the choice lasts for this page only.
    }
  }
</script>

<header class="status">
  <a class="brand" href={link("/")}>EarningsWatch</a>
  <span title="The newest quarter in the data ends {status.newest}">
    <span class="hide-sm">Most companies have reported through</span><span class="show-sm">Data to</span>{" "}<span data-testid="through">{status.through}</span>
  </span>
  <span class="ok"><span class="hide-sm">Pipeline checked {day(status.exported_at)}</span>{" "}{utcTime(status.exported_at)}</span>
  <button class="theme" type="button" onclick={toggle} aria-pressed={theme === "dark"}>
    {theme === "dark" ? "Paper" : "Terminal"}
  </button>
</header>

<style>
  .status {
    display: flex; flex-wrap: wrap; gap: 4px 20px; align-items: center; padding: 8px 20px;
    border-bottom: 1px solid var(--rule); font-size: 13px; color: var(--muted);
  }
  .brand { color: var(--accent); font-weight: 600; margin-right: auto; text-decoration: none; }
  .ok::before { content: "\25CF"; color: var(--up); margin-right: 6px; }
  .theme {
    background: none; border: 1px solid var(--rule); color: var(--text); font: inherit;
    font-size: 12px; padding: 2px 8px; cursor: pointer;
  }
  .show-sm { display: none; }
  @media (max-width: 760px) {
    .show-sm { display: inline; }
    .brand { flex-basis: 100%; }
  }
</style>
