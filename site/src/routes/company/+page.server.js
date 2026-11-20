import { companyList } from "#lib/server/export.js";

export async function load() {
  return { companies: await companyList() };
}
