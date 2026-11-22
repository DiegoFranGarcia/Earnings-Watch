# Chaos drills

Each drill breaks one thing on purpose and records which layer caught it. The standard, from the
project plan: every fault is caught at the right layer, the marts are unchanged, and an alert
arrives.

| Drill | Caught by | Marts | Alert |
|---|---|---|---|
| A truncated ZIP | The download check (Stage 1): size and archive validation | Untouched: nothing landed | Task failure |
| The same file twice | Idempotent loads: delete, `COPY ... FORCE`, count, commit | Identical fingerprints | None needed: nothing is wrong |
| Half a quarter | The volume gate in `dbt_build` | Identical fingerprints | Discord, within a minute |
| A day with too few filings | The volume gate in `dbt_build` (its daily check) | Identical fingerprints; the live site kept its export | Discord, within a minute |
| Columns reordered by the SEC | The header check in the Spark job | Untouched: no silver written | Task failure |

## Half a quarter (2026-11-09)

Deleted 60% of 2026q3's numbers from `RAW.FSDS_NUM` (2,343,006 rows, chosen by hash), leaving
1,562,391, as if the SEC had published a partial file. Then triggered `dbt_build`.

| Time (UTC) | `quarterly_facts` 2026q3 | Ratio to 2025q3 | Outcome |
|---|---|---|---|
| 22:43 | 3,905,397 | 1.05 | pass |
| 22:48 | 1,562,391 | 0.42 | **fail**: dbt did not run; Discord alert |
| 22:49 | 3,905,397 | 1.05 | pass, after reloading 2026q3 from silver |

The reload's success triggered `dbt_build` by itself. Every mart's fingerprint (`HASH_AGG` of
every row) was identical before the drill, during it, and after the rebuild:

| Mart | Rows | Fingerprint |
|---|---|---|
| mart_earnings_quality | 622,820 | 4560974356956372534 |
| mart_restatements | 328,872 | -6315433423800887193 |
| mart_filing_timeliness | 154 | -8564263043988964721 |

## A day with too few filings (2026-11-21)

The first time the gate's daily check fired, and the first drill with the public site at the end
of the chain: the question was whether a failed gate also leaves the site as it was.

Deleted 2,836 of 2026-11-20's rows from `RAW.DAILY_INDEX` (every row of 1,960 of the day's 2,822
filings, chosen by hash), as if EDGAR's index for the day had arrived incomplete. Then triggered
`dbt_build`.

| When (UTC) | `daily_filings` 2026-11-20 | Ratio to the median of the 20 days before | Outcome |
|---|---|---|---|
| Before | 2,822 | 0.75 | pass (a quiet Friday) |
| 20:30 | 862 | 0.23 | **fail**: no retry, dbt did not run; Discord alert |
| 20:40 | 2,822 | 0.75 | pass, after reloading November from silver |

The alert, as it arrived: "volume check failed; the marts keep their last good data:
daily_filings 2026-11-20: 862 (23% of usual)". `volume_gate` failed on its first try, in 15
seconds; `publish`, the only task that announces new marts, and the 81 other tasks after the gate
were marked `upstream_failed`. `AUDIT.DQ_RESULTS` holds both checks for the run: the daily check
failed at 0.2305, the quarterly check (2026q3, untouched) passed at 1.05.

**Nothing downstream changed.** Each table's row count and fingerprint (`HASH_AGG` of every row)
was compared with its value before the drill, and Snowflake's record of when the table last
changed shows nothing touched it:

| Table | Rows | During the drill | Last changed (UTC) | After the recovery |
|---|---|---|---|---|
| mart_earnings_quality | 622,820 | same | 13:55 | same, rebuilt 20:45 |
| mart_restatements | 328,872 | same | 13:53 | same, rebuilt 20:44 |
| mart_filing_timeliness | 154 | same | 13:55 | same, rebuilt 20:46 |
| export_screener | 7,055 | same | 13:55 | same, rebuilt 20:46 |
| export_company_quarters | 135,191 | same | 13:56 | same, rebuilt 20:47 |
| export_company_history | 12,383 | same | 13:56 | same, rebuilt 20:47 |
| export_restatements_by_year | 522 | same | 13:55 | same, rebuilt 20:46 |
| export_restatements_largest | 994 | same | 13:55 | same, rebuilt 20:45 |
| export_filing_timeliness | 113 | same | 13:55 | same, rebuilt 20:45 |
| export_pipeline_health | 30 | same | 13:55 | changed, as it should: today's row now counts the failed check |

"Last changed" is the last build before the drill, six and a half hours earlier. The site was
unchanged too: the live `site.json` and the export pointer in S3 named the same export
(`asset_triggered__2026-11-21T13:57:27…`) before and during the drill, and no deploy ran.

<details>
<summary>The fingerprints</summary>

| Table | Fingerprint, before and during |
|---|---|
| mart_earnings_quality | 4560974356956372534 |
| mart_restatements | -6315433423800887193 |
| mart_filing_timeliness | 3405811196753959442 |
| export_screener | -4620413257527467148 |
| export_company_quarters | -8941730803225377257 |
| export_company_history | -6076661271869010732 |
| export_restatements_by_year | 2957359539861591770 |
| export_restatements_largest | -6865685053910213043 |
| export_filing_timeliness | 5914382078770716399 |
| export_pipeline_health | 4688656644575564671 |

`RAW.DAILY_INDEX`, every column but `_loaded_at`, before the drill and after the recovery:
3656571601369447069 (2,465,337 rows).

Each drill compares with its own "before": mart_filing_timeliness differs from its 2026-11-09
value because it has been rebuilt since with newer data and code.

</details>

**Recovery took the normal path,** with no step by hand after the reload:
`snowflake_load_daily_index` with `{"months": "2026-11"}` replaced November in one transaction (10
seconds; committed only because the rows matched the silver files), which started `dbt_build`; the
gate passed, the build published, and the site redeployed (export
`asset_triggered__2026-11-21T20:48:03…`), its `verify` job confirming that the live site served
exactly what was deployed. Afterwards nine tables matched their pre-drill fingerprints, and
`RAW.DAILY_INDEX` matched a copy taken before the drill row for row (leaving out `_loaded_at`, the
load time): the same 2,465,337 rows and none on one side only.

**How it was run safely.** A zero-copy clone of `RAW.DAILY_INDEX` was taken and checked identical
first, so the data could be put back with one `ALTER TABLE ... SWAP WITH` if the reload failed.
The Airflow host was stopped while the data was broken, so nothing could build until the gate's
query, run by hand first, showed the day would fail. Each step ran as the role that owns the
table (LOADER for RAW, REPORTER to read the marts). The drill's runs are named `manual__drill-`,
so they can be told apart from real failures. The drill ended with the comparison against the
clone, before the next scheduled start; the clone is kept until the next morning's run is green.

## Columns reordered (2026-11-09)

Took 2026q3's real `sub.txt` from bronze, swapped `cik` and `name` (header and data, as a real
reordering would), and ran the real Spark job on it:

    HeaderMismatch: .../sub.txt: columns changed (same columns in a different order)

No silver was written. Before the header check, Spark mapped columns by position and ignored the
header's names: company names would have loaded into `cik`, `try_cast` would have turned every
CIK into a null, and every filing would have been quietly unlinked from its company.

## The same file twice

2026q3 has been loaded repeatedly: always 3,905,397 rows. Reloading seven quarters (2025q1 to
2026q3, 24.8 million rows) left every quarter's fingerprint identical (Stage 5, Part 5.5).

## Faults found without a drill

Real problems caught while building, each now guarded:

- **dbt imported an Airflow DAG.** dbt imports every module named `dbt_*` on the Python path to
  discover plugins; a DAG file named `dbt_build.py` broke CI. Renamed, and a test forbids it.
- **An alert webhook was a placeholder.** Alerts looked configured but had never been delivered.
  A delivery test found it; the rule since: an alert path is not done until a real alert arrives.
- **Tests ran before the tables they check.** On 2026-11-21 the nightly build stopped on two
  relationship tests that judged the day before's tables, and published nothing; fixed by running
  tests with several parents after all of them ([the incident](incidents/2026-11-21.md)).
- **Expired AWS logins on a laptop.** Scheduled runs fail when `aws login` lapses. Diagnosed from
  a retrying task; Stage 7 replaces the login with an EC2 instance role. One such failure, before
  alerts existed, lost a day of the daily index for two weeks; sec_daily_index now checks every
  morning that recent days have landed ([the incident](incidents/2026-11-05.md)).
