// The theme a visitor chose last time, before the page paints. Light unless they chose dark;
// if storage is blocked (a private window, say), the site simply opens light.
try {
  if (localStorage.getItem("ew-theme") === "dark") document.documentElement.dataset.theme = "dark";
} catch {}
