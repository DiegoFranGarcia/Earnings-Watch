<script>
  import "@fontsource/ibm-plex-mono/latin-400.css";
  import "@fontsource/ibm-plex-mono/latin-500.css";
  import "@fontsource/ibm-plex-mono/latin-600.css";
  import "@fontsource/ibm-plex-sans/latin-400.css";
  import "@fontsource/ibm-plex-sans/latin-500.css";
  import "../app.css";
  import Shortcuts from "#lib/components/Shortcuts.svelte";
  import StatusBar from "#lib/components/StatusBar.svelte";
  import Tabs from "#lib/components/Tabs.svelte";

  let { data, children } = $props();

  // Marks the page interactive (hydrated): the browser tests wait for this before pressing keys.
  $effect(() => {
    document.documentElement.dataset.ready = "true";
  });
</script>

<StatusBar status={data.status} />
{@render children()}
<Tabs />
<Shortcuts />
