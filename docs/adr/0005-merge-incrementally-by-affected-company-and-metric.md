# 5. Merge the company-quarter fact incrementally by affected (company, metric)

## Context
A filing accepted this week can restate a quarter from years ago, so "the last N days" misses
restatements. Derived quarters also depend on their neighbours: a new H1 changes Q2 (H1 - Q1)
and Q3 (9M - H1), so recomputing only the periods that received new numbers leaves others stale.

## Decision
fct_company_quarter_metrics is incremental with delete+insert on unique key (cik, metric). Each
run finds the pairs with any number loaded since the last run (via last_loaded_at, carried from
RAW through every intermediate model) and rebuilds each pair's whole quarterly history.

## Consequences
- Correct by construction: after a real reload of 2026q3, the incremental table matched a full
  recomputation with 0 mismatches.
- Coarse for the newest quarter: that reload rewrote 2.4m of 4.6m rows (59,000 active pairs'
  full histories). One company's amendment rewrites only its own pairs.
- A tighter key, (cik, metric, fiscal year), would also be correct, because derivations never
  cross a fiscal year; it needs every row to have a fiscal year first, since a null key in
  delete+insert silently fails to delete.
