// The site is prerendered to static files and served by GitHub Pages under /Earnings-Watch/
// (a project site: the base path is the repository's name, case-sensitive). Every page carries
// a Content-Security-Policy with a hash for each script SvelteKit writes: nothing loads from
// anywhere but the site itself. (SvelteKit 3 takes its options here, not in svelte.config.js.)
import adapter from "@sveltejs/adapter-static";
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

/** @type {"" | `/${string}`} */
const base = /** @type {any} */ (process.env.BASE_PATH ?? "/Earnings-Watch");
if (base && !base.startsWith("/")) throw new Error(`BASE_PATH must start with "/": ${base}`);

export default defineConfig({
  plugins: [
    sveltekit({
      adapter: adapter({ pages: "build", assets: "build", strict: true }),
      paths: { base },
      prerender: {
        // The dbt docs sit beside the app (build_site.py puts them at /dbt-docs/), not inside it.
        handleHttpError: ({ path, message }) => {
          if (path.startsWith(`${base}/dbt-docs/`)) return;
          throw new Error(message);
        },
        handleMissingId: "fail",
      },
      csp: {
        mode: "hash",
        directives: {
          "default-src": ["self"],
          "script-src": ["self"],
          "style-src": ["self", "unsafe-inline"],
          "img-src": ["self", "data:"],
          "font-src": ["self"],
          "connect-src": ["self"],
          "object-src": ["none"],
          "base-uri": ["none"],
          "form-action": ["none"],
        },
      },
    }),
  ],
});
