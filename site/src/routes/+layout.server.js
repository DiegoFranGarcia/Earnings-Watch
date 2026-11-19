import { status } from "#lib/server/export.js";

export async function load() {
  return { status: await status() };
}
