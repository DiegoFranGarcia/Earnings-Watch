import { error } from "@sveltejs/kit";
import { company, companyList } from "#lib/server/export.js";

/** One page per company the screener covers, each prerendered: /company/<CIK>/. */
export async function entries() {
  return (await companyList()).map((c) => ({ cik: String(c.cik) }));
}

export async function load({ params }) {
  if (!/^\d{1,10}$/.test(params.cik)) error(404, "Not a CIK");
  const found = await company(Number(params.cik));
  if (!found) error(404, "No company with this CIK on the site");
  return { cik: Number(params.cik), ...found };
}
