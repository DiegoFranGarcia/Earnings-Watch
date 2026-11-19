import facts from "#lib/facts.json";
import { overview } from "#lib/server/export.js";

export async function load() {
  return { overview: await overview(), facts };
}
