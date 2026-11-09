# 11. Check source headers before parsing

## Context
The Spark job reads the SEC's files with an explicit schema, which Spark maps by position: it
skips the header row without comparing its names. An added column would quarantine every row
under a misleading message; a renamed or reordered one would load values into the wrong fields
with no error at all. The SEC has changed these files before (December 2024 added `segments`).

## Decision
Before parsing sub.txt or num.txt, the job reads the first line and fails with HeaderMismatch
unless it is exactly the expected columns, in order, naming what was added, missing or reordered.

## Consequences
- Drilled on a real file: swapping cik and name now fails before reading a row, with no silver
  written. It would previously have nulled every CIK silently.
- Reading one line costs almost nothing, even for a file of hundreds of megabytes.
- Any future change by the SEC stops the pipeline until the schema is updated deliberately.
