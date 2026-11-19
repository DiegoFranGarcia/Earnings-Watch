// The site's pages, in tab order: each one's shortcut is its position (0 to 6). route is the
// SvelteKit route ID: it says which tab is current even while a page is being prerendered.
import { resolve } from "$app/paths";

/** @type {{ route: import("$app/types").RouteId, label: string }[]} */
export const PAGES = [
  { route: "/", label: "Overview" },
  { route: "/screener", label: "Screener" },
  { route: "/company", label: "Company" },
  { route: "/restatements", label: "Restatements" },
  { route: "/timeliness", label: "Timeliness" },
  { route: "/pipeline", label: "Pipeline" },
  { route: "/sql", label: "SQL" },
];

/** A page's URL, under the base path and ending in a slash, as GitHub Pages serves folders. */
export function link(/** @type {import("$app/types").RouteId} */ route) {
  const url = resolve(route);
  return url.endsWith("/") ? url : `${url}/`;
}

/** The dbt docs: beside the app (build_site.py puts them there), not one of its routes. */
export function dbtDocs() {
  return `${link("/")}dbt-docs/`;
}
