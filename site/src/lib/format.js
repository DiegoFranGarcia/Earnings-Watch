// Formatting for every number and date on the site. Dates are always shown in UTC: a quarter
// that ends on 2026-03-31 must not become "March 30" in New York.

const MINUS = "−";

/** @param {number | null | undefined} dollars */
export function money(dollars) {
  if (dollars == null || Number.isNaN(dollars)) return "—";
  const sign = dollars < 0 ? MINUS : "";
  const abs = Math.abs(dollars);
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(abs >= 1e10 ? 0 : 1)}bn`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(abs >= 1e8 ? 0 : 1)}m`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(0)}k`;
  return `${sign}$${abs.toFixed(0)}`;
}

/** A change in dollars, always signed: +$12m, −$3.4m. @param {number | null | undefined} dollars */
export function moneyChange(dollars) {
  if (dollars == null || Number.isNaN(dollars)) return "—";
  return (dollars >= 0 ? "+" : "") + money(dollars);
}

/**
 * Growth from prior to now, as a whole percent; none when the prior value is not positive.
 * @param {number | null | undefined} now
 * @param {number | null | undefined} prior
 */
export function growth(now, prior) {
  if (now == null || prior == null || prior <= 0) return null;
  return Math.round((now / prior - 1) * 100);
}

/** @param {number | null} p a fraction, 0.141 -> "14.1%" */
export function percent(p, digits = 1) {
  return p == null ? "—" : `${(p * 100).toFixed(digits)}%`;
}

/** @param {number} n */
export function count(n) {
  return n.toLocaleString("en-US");
}

/** 188865271 -> "188.9M" @param {number} n */
export function compact(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
}

/** YYYY-MM-DD, in UTC. @param {string | Date | null | undefined} value */
export function day(value) {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  return d.toISOString().slice(0, 10);
}

/** "06:05 UTC" @param {string} iso */
export function utcTime(iso) {
  return `${new Date(iso).toISOString().slice(11, 16)} UTC`;
}

/** Small amounts with cents: 1.374 -> "$1.37". @param {number | null | undefined} dollars */
export function cents(dollars) {
  if (dollars == null || Number.isNaN(dollars)) return "—";
  return `$${dollars.toFixed(2)}`;
}
