<script>
  // Keyboard shortcuts: 0-6 open the pages in tab order, / focuses the search box, ? lists them.
  // Never while typing in a box, and never with Ctrl, Cmd or Alt held: the browser owns those
  // (Ctrl/Cmd+1-9 switch tabs).
  import { goto } from "$app/navigation";
  import { PAGES, link } from "#lib/pages.js";

  /** @type {HTMLDialogElement | undefined} */
  let dialog = $state();

  /** @param {KeyboardEvent} e */
  function onkeydown(e) {
    const target = /** @type {HTMLElement} */ (e.target);
    if (target.closest?.("input, textarea, select, [contenteditable]")) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "?") {
      e.preventDefault();
      if (dialog?.open) dialog.close();
      else dialog?.showModal();
      return;
    }
    if (dialog?.open) return;
    if (e.key === "/") {
      const search = /** @type {HTMLElement | null} */ (document.querySelector("[data-search]"));
      if (search) {
        e.preventDefault();
        search.focus();
      }
      return;
    }
    if (/^[0-6]$/.test(e.key)) {
      e.preventDefault();
      goto(link(PAGES[Number(e.key)].route));
    }
  }
</script>

<svelte:window {onkeydown} />

<dialog bind:this={dialog} aria-labelledby="shortcuts-title">
  <h2 id="shortcuts-title">Keyboard shortcuts</h2>
  <dl>
    <dt><kbd>0</kbd>&ndash;<kbd>6</kbd></dt>
    <dd>Open a page: {PAGES.map((p) => p.label.toLowerCase()).join(", ")}</dd>
    <dt><kbd>/</kbd></dt>
    <dd>Search companies</dd>
    <dt><kbd>?</kbd></dt>
    <dd>Show this list</dd>
    <dt><kbd>Esc</kbd></dt>
    <dd>Close</dd>
  </dl>
  <p class="note">Shortcuts pause while you type in a box, and never take over Ctrl, Cmd or Alt.</p>
  <form method="dialog"><button>Close</button></form>
</dialog>
<p class="hint hide-sm">Press <kbd>?</kbd> for shortcuts</p>

<style>
  dialog {
    background: var(--panel); color: var(--text); border: 1px solid var(--accent-dim);
    padding: 18px 22px; max-width: 540px;
  }
  dialog::backdrop { background: var(--shade); }
  h2 { margin: 0 0 12px; font-size: 15px; }
  dl { display: grid; grid-template-columns: auto 1fr; gap: 8px 16px; margin: 0; font-size: 13.5px; }
  dd { margin: 0; font-family: "IBM Plex Sans", system-ui, sans-serif; }
  kbd { border: 1px solid var(--rule); padding: 0 5px; font: inherit; color: var(--accent); }
  .note { color: var(--muted); font-size: 12.5px; margin: 14px 0 10px; }
  form button {
    font: inherit; font-size: 12.5px; background: none; color: var(--text);
    border: 1px solid var(--rule); padding: 3px 10px; cursor: pointer;
  }
  .hint { position: fixed; right: 14px; bottom: 58px; font-size: 12px; color: var(--muted); margin: 0; }
</style>
