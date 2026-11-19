<script>
  import { page } from "$app/state";
  import { PAGES, link } from "#lib/pages.js";
</script>

<nav class="tabs" aria-label="Pages">
  {#each PAGES as p, i (p.route)}
    <a href={link(p.route)} aria-current={page.route.id === p.route ? "page" : undefined}>
      <kbd aria-hidden="true">{i}</kbd>{p.label}
    </a>
  {/each}
</nav>

<style>
  .tabs {
    position: fixed; left: 0; right: 0; bottom: 0; display: flex; background: var(--panel);
    border-top: 1px solid var(--rule); overflow-x: auto; z-index: 5;
  }
  a {
    display: flex; gap: 8px; align-items: center; padding: 12px 16px; text-decoration: none;
    color: var(--text); border-right: 1px solid var(--rule); white-space: nowrap; font-size: 13.5px;
  }
  a:hover { background: var(--bg); }
  a[aria-current="page"] { color: var(--accent); box-shadow: inset 0 2px 0 var(--accent); }
  kbd { color: var(--muted); font: inherit; font-size: 11.5px; border: 1px solid var(--rule); padding: 0 5px; }
  a[aria-current="page"] kbd { color: var(--accent); border-color: var(--accent-dim); }
</style>
