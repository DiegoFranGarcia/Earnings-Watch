<script>
  import { count } from "#lib/format.js";

  /** @type {{ summary: Record<string, { universe: number, flagged: number }>, view: string, onview: (v: string) => void }} */
  let { summary, view, onview } = $props();
  const QUERY = "> SCREEN profits rising, cash not <GO>";
  const names = { latest: "after restatements", first_reported: "as first reported" };
  const now = $derived(summary[view]);
</script>

<section class="hero">
  <p class="prompt"><span class="typed" style="--n: {QUERY.length}" aria-label="Screen: profits rising, cash not">{QUERY}</span><span class="cursor" aria-hidden="true"></span></p>
  <h1>Which companies report rising profits their cash doesn't back up?</h1>
  <div class="answer">
    <div class="n" data-testid="flagged">{count(now.flagged)}</div>
    <div class="ctx prose">
      <p class="of">
        of <span data-testid="universe">{count(now.universe)}</span> companies up to date with their filings are flagged,
        <span data-testid="view-name">{names[/** @type {"latest" | "first_reported"} */ (view)]}</span>.
      </p>
      <p class="def">
        Flagged means net income is up on a year ago while operating cash flow isn't, and the
        difference, accruals, is more than 10% of total assets.
      </p>
    </div>
  </div>
  <div class="viewtoggle" role="group" aria-label="Which figures">
    <button type="button" aria-pressed={view === "first_reported"} onclick={() => onview("first_reported")}>As first reported</button>
    <button type="button" aria-pressed={view === "latest"} onclick={() => onview("latest")}>After restatements</button>
  </div>
</section>

<style>
  .hero { padding: 56px 0 40px; border-bottom: 1px solid var(--rule); }
  .prompt { color: var(--accent); margin: 0 0 18px; white-space: nowrap; overflow: hidden; }
  /* Monospace, so the query types itself by widening one character at a time: under a second,
     with the text already in the page, and not at all for reduced motion. */
  .typed {
    display: inline-block; vertical-align: bottom; overflow: hidden; white-space: nowrap;
    width: calc(var(--n) * 1ch); animation: type 0.85s steps(var(--n)) both;
  }
  @keyframes type { from { width: 0; } }
  .cursor {
    display: inline-block; width: 0.6em; height: 1.1em; background: var(--accent);
    vertical-align: -0.2em; margin-left: 2px; animation: blink 1.1s steps(1) infinite;
  }
  @keyframes blink { 50% { opacity: 0; } }
  @media (prefers-reduced-motion: reduce) {
    .typed, .cursor { animation: none; }
  }
  h1 {
    font-size: clamp(30px, 5.2vw, 58px); line-height: 1.05; font-weight: 600;
    letter-spacing: -0.02em; margin: 0 0 28px; max-width: 18ch;
  }
  .answer { display: grid; grid-template-columns: auto 1fr; gap: 6px 24px; align-items: end; max-width: 820px; }
  .n {
    font-size: clamp(44px, 8vw, 92px); line-height: 0.95; color: var(--accent); font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .ctx p { margin: 0; max-width: 48ch; }
  .of { font-size: 21px; line-height: 1.3; margin-bottom: 8px !important; }
  .def { font-size: 15.5px; color: var(--muted); }
  .viewtoggle { margin-top: 26px; display: inline-flex; border: 1px solid var(--rule); }
  .viewtoggle button {
    font: inherit; font-size: 13px; background: none; color: var(--muted); border: 0;
    padding: 6px 12px; cursor: pointer;
  }
  .viewtoggle button[aria-pressed="true"] { background: var(--accent); color: var(--on-accent); }
  @media (max-width: 760px) {
    .hero { padding-top: 36px; }
    .answer { grid-template-columns: 1fr; }
  }
</style>
