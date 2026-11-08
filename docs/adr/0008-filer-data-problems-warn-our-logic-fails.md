# 8. Problems in filer data warn; problems in our logic fail

## Context
The full history surfaced issues one quarter never showed: periods ending after their filing,
numbers for filings the SEC never listed, impossible durations, simultaneous filings recording
different attributes, unbalanced balance sheets, repeated index listings. Failing the build on
any of these would block the warehouse on other people's typos; silencing them would hide them.

## Decision
Tests that check data the SEC or filers produced have severity warn and document their counts and
cause in a comment. Tests that check our transformations (uniqueness after deduplication,
contiguous company history, contracts, unit tests) fail. Every finding is traced to its rows,
and cross-checked where possible, before a test's severity is set.

## Consequences
- dbt build is green with 9 documented warnings, each a finding rather than noise.
- The 2013q1 orphan numbers (1,953) were confirmed against Spark's reconciliation record before
  their test was set to warn.
