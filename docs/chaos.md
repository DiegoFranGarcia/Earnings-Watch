# Chaos drills

Each drill breaks one thing on purpose and records which layer caught it. The standard, from the
project plan: every fault is caught at the right layer, the marts are unchanged, and an alert
arrives.

| Drill | Caught by | Marts | Alert |
|---|---|---|---|
| A truncated ZIP | The download check (Stage 1): size and archive validation | Untouched: nothing landed | Task failure |
| The same file twice | Idempotent loads: delete, `COPY ... FORCE`, count, commit | Identical fingerprints | None needed: nothing is wrong |
| Half a quarter | The volume gate in `dbt_build` | Identical fingerprints | Discord, within a minute |
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
- **Expired AWS logins on a laptop.** Scheduled runs fail when `aws login` lapses. Diagnosed from
  a retrying task; Stage 7 replaces the login with an EC2 instance role.
