# 9. Group filer statuses by deadline for trends

## Context
Filer status codes changed meaning over time: 10-Ks under 5-SML fell from 2,183 to 416 in 2018
as 4-NON rose from 517 to 2,113, and 2-ACC fell from 1,233 to 784 in 2020, while total filings
stayed steady. These are the SEC's 2018 and 2020 rule changes re-labelling companies, not data
errors.

## Decision
filing_deadlines maps each status to a filer_group by deadline: large_accelerated (1-LAF),
accelerated (2-ACC, 3-SRA), non_accelerated (4-NON, 5-SML). mart_filing_timeliness keeps its
grain (status, form, year) and carries filer_group for trends.

## Consequences
- On-time classification is unaffected: re-coded statuses share deadlines.
- Trends must sum by filer_group; a status-code trend shows labels disappearing, not behaviour.
