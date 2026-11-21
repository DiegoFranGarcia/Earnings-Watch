# 10. A circuit breaker before the marts publish

## Context
Count checks prove that RAW holds what silver held, but a partial file from the SEC loads
perfectly and passes them. A pipeline that publishes wrong numbers fails silently; one that
stops fails loudly.

## Decision
dbt_build's first task is a volume gate. It compares the newest day of filings with the median of
the 20 business days before it (fail under 50%, warn under 75%; no upper bound, since deadline
days are several times busier), and the newest quarter's numbers with the same quarter a year
earlier (fail under 50% or over 200%, warn under 75% or over 150%). A failure stops the build
with no retry: the marts keep their last good data and an alert fires. Every result is recorded
in AUDIT.DQ_RESULTS. After investigating, a person can publish anyway with
{"accept_volume": true}.

## Consequences
- Drilled: 60% of 2026q3 deleted, the gate failed at 42%, the marts' fingerprints were unchanged,
  and a reload healed everything without further steps.
- Drilled again 2026-11-21 on the daily check, with the public site at the end of the chain: about
  70% of a day's filings deleted, the gate failed at 23% with no retry, the marts and the live site
  kept the last good export, and reloading the month redeployed the site by itself
  ([chaos drills](../chaos.md)).
- A genuinely quiet day (Christmas Eve) needs a human decision; the override records it.
- The gate costs about a cent per run.
