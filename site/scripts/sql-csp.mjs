// Allow WebAssembly and same-site workers on the SQL page, and on no other page. SvelteKit sets
// one Content-Security-Policy for the whole site (kit.csp), written into each page as a <meta>
// tag; a second <meta> could only tighten it (the browser enforces every policy it is given), so
// this replaces the SQL page's policy after the build, adding exactly 'wasm-unsafe-eval' to
// script-src and worker-src 'self'. DuckDB's engine compiles WebAssembly in its worker, which
// some browsers hold to the page's policy. Every other page's file is left untouched.
// Runs after vite build (npm run build); the browser tests check both directions.
import fs from "node:fs";
import path from "node:path";

export const PAGE = "sql/index.html";
const META = /(<meta http-equiv="content-security-policy" content=")([^"]*)(">)/;

/**
 * The SQL page's policy: the site's, plus 'wasm-unsafe-eval' in script-src and worker-src 'self'.
 * @param {string} policy
 */
export function allowWasm(policy) {
  const directives = policy.split(";").map((d) => d.trim()).filter(Boolean);
  const at = directives.findIndex((d) => d.startsWith("script-src "));
  if (at < 0) throw new Error(`no script-src in ${policy}`);
  if (directives.some((d) => d.startsWith("worker-src ") || d.includes("'wasm-unsafe-eval'"))) {
    throw new Error("the policy already mentions worker-src or 'wasm-unsafe-eval': run on a fresh build");
  }
  directives[at] = `${directives[at]} 'wasm-unsafe-eval'`;
  directives.splice(at + 1, 0, "worker-src 'self'");
  return directives.join("; ");
}

/** @param {string} html */
export function policyOf(html) {
  const match = META.exec(html);
  if (!match) throw new Error("no Content-Security-Policy <meta> tag");
  return match[2];
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const file = path.resolve(process.argv[2] ?? "build", PAGE);
  const html = fs.readFileSync(file, "utf8");
  const before = policyOf(html);
  fs.writeFileSync(file, html.replace(META, (_, open, policy, close) => `${open}${allowWasm(policy)}${close}`));
  console.log(`${PAGE}: added 'wasm-unsafe-eval' and worker-src 'self' to its policy (${before.length} -> ${policyOf(fs.readFileSync(file, "utf8")).length} characters)`);
}
