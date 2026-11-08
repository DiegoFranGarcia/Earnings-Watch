# 6. Keep first-reported and latest values side by side

## Context
Companies restate. A historical signal computed from today's figures uses information that did
not exist at the time (look-ahead bias), so it overstates what an investor could have known.

## Decision
Every fact keeps every reported version (int_facts__versions). Quarters, the company-quarter
fact and the earnings-quality mart carry both first-reported and latest values, with the time
each became knowable (first_known_at, latest_known_at). The mart is a reporting_view dimension
(first_reported, latest) computed by one shared calculation, so the two views cannot drift.

## Consequences
- Measured: of 4,206 flags in the latest view, 420 (10%) were not knowable at the time, and the
  latest view misses 333 flags investors could have seen.
- Changes within var restatement_threshold (0.5%) are rounding, not restatement: about 29% of
  all changed values were rounding only.
