"""Write a small, invented export in the shape of the real one, for building and testing the site.

The site's CI check (`site`) builds the app against this, never against real data. Every table
has exactly the columns and types its dbt contract declares (dbt/models/exports/_exports.yml),
so a contract change that the site has not caught up with fails the build, not the live site.
Company names are invented ("Fixture Co 01") so nothing here can be mistaken for real figures.

It writes what build_site.py lays out from a real export (data/, dbt-docs/, site.json), so the
app's build can be added beside it as the deploy does, and tested where it will be served:

    uv run python scripts/make_site_fixture.py --out site/fixture
    cd site && EW_DATA_DIR=fixture npm run build
    python3 ../scripts/build_site.py --add-app build --out fixture
    npm test
"""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import hashlib
import json
import random
import re
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "dbt" / "models" / "exports" / "_exports.yml"
GROUPS = [
    "Technology",
    "Manufacturing",
    "Life Sciences",
    "Trade & Services",
    "Energy & Transportation",
]
FILERS = ["large_accelerated", "accelerated", "non_accelerated"]
VIEWS = ["first_reported", "latest"]


def arrow_type(data_type: str) -> pa.DataType:
    """The Arrow type the export writes for a dbt contract type (Snowflake's own mapping)."""
    t = data_type.split("#")[0].strip().lower()
    if t in ("bigint", "integer"):
        return pa.int64()
    if t == "double":
        return pa.float64()
    if t == "boolean":
        return pa.bool_()
    if t == "varchar":
        return pa.string()
    if t == "date":
        return pa.date32()
    if t == "timestamp_ntz":
        return pa.timestamp("ns")
    match = re.fullmatch(r"decimal\((\d+),\s*(\d+)\)", t)
    if match:
        return pa.decimal128(int(match[1]), int(match[2]))
    raise ValueError(f"no Arrow type for the contract type {data_type!r}")


def contract() -> dict[str, list[tuple[str, pa.DataType]]]:
    models = yaml.safe_load(CONTRACT.read_text())["models"]
    return {
        m["name"]: [(c["name"], arrow_type(c["data_type"])) for c in m["columns"]] for m in models
    }


def quarter_end(year: int, quarter: int) -> dt.date:
    """The last day of a calendar quarter; quarter may run past 4 into later years."""
    year, quarter = year + (quarter - 1) // 4, (quarter - 1) % 4 + 1
    first_of_next = dt.date(year + quarter // 4, quarter % 4 * 3 + 1, 1)
    return first_of_next - dt.timedelta(days=1)


def ntz(*parts: int) -> dt.datetime:
    """A TIMESTAMP_NTZ: Snowflake's timestamps without a time zone, as the export writes them."""
    return dt.datetime(*parts)  # noqa: DTZ001


def money(value: float) -> decimal.Decimal:
    return decimal.Decimal(f"{value:.4f}")


# Two companies that test the site's warnings: one behind on its filings (its latest quarter
# 2025-12-31, three quarters before most), one with implausible figures (net income above
# twice its assets, as a units mistake would make it).
BEHIND, IMPLAUSIBLE = 37, 36


def rows(rng: random.Random) -> dict[str, list[dict]]:
    """Invented rows for every table: 40 companies, 12 quarters each (company 37: 9)."""
    # Twelve calendar quarter ends, 2023-12-31 to 2026-09-30.
    quarter_ends = [quarter_end(2023, 4 + q) for q in range(12)]
    out: dict[str, list[dict]] = {name: [] for name in contract()}
    for i in range(1, 41):
        cik = 1_000_000 + i
        name, group, filer = f"Fixture Co {i:02d}", GROUPS[i % len(GROUPS)], FILERS[i % len(FILERS)]
        flagged = i % 4 == 0
        base_income = rng.uniform(5e6, 4e8)
        latest = quarter_ends[-4] if i == BEHIND else quarter_ends[-1]
        for q, end in enumerate(quarter_ends):
            if end > latest:
                continue
            income = base_income * (1 + (0.06 if flagged else 0.01) * q)
            cash = income * (0.45 if flagged else 1.05)
            restated = q == 6 and i % 5 == 0
            out["export_company_quarters"].append(
                {
                    "cik": cik,
                    "period_end": end,
                    "fiscal_year": end.year,
                    "fiscal_quarter": (end.month - 1) // 3 + 1,
                    "net_income_first_reported": money(income),
                    "net_income_latest": money(income * (0.9 if restated else 1)),
                    "operating_cash_flow_first_reported": money(cash),
                    "operating_cash_flow_latest": money(cash),
                    "is_net_income_restated": restated,
                    "is_operating_cash_flow_restated": False,
                    "is_derived": q % 4 == 3,
                    "company_quarter_key": f"{cik}|{end}",
                }
            )
        filed = ntz(2026, 2, 26, 21, 15) if i == BEHIND else ntz(2026, 11, 2, 21, 15)
        for view in VIEWS:
            ttm = base_income * 4.6
            flag_here = flagged and not (
                view == "latest" and i == 8
            )  # one flag gone after a restatement
            out["export_screener"].append(
                {
                    "cik": cik,
                    "reporting_view": view,
                    "period_end": latest,
                    "fiscal_year": latest.year,
                    "fiscal_quarter": (latest.month - 1) // 3 + 1,
                    "known_at": filed,
                    "sic": 3674,
                    "industry_title": "SEMICONDUCTORS",
                    "filer_status": "1-LAF",
                    "ttm_net_income": money(ttm),
                    "prior_ttm_net_income": money(ttm * 0.78),
                    "ttm_operating_cash_flow": money(ttm * (0.45 if flagged else 1.05)),
                    "prior_ttm_operating_cash_flow": money(ttm * (0.52 if flagged else 0.98)),
                    "average_total_assets": money(ttm * (0.4 if i == IMPLAUSIBLE else 3.5)),
                    "accruals": money(ttm * 0.55),
                    "accruals_to_assets": round(0.11 + i / 400, 4)
                    if flag_here
                    else round(0.02 + i / 1000, 4),
                    "is_flagged": flag_here,
                    "is_implausible": i == IMPLAUSIBLE,
                    "company_name": name,
                    "industry_group": group,
                    "filer_group": filer,
                    "screener_key": f"{cik}|{view}",
                }
            )
        out["export_company_history"].append(
            {
                "company_key": f"k{cik}-1",
                "cik": cik,
                "version_number": 1,
                "company_name": name,
                "sic": 3674,
                "industry_title": "SEMICONDUCTORS",
                "filer_status": "1-LAF",
                "valid_from": ntz(2009, 4, 1),
                "valid_to": None,
                "is_current": True,
            }
        )
    # Restatements, in round numbers the site's tests can check: each year, for net income, 60
    # amendments, 540 later-filing changes and 200 tag switches (2026, to date: about half), at
    # 50, 400 and 150 companies counted once under their first kind, of 4,000 companies
    # reporting the figure (fewer in 2009 and 2010, as XBRL tagging phased in). Revenue and
    # operating cash flow: the same, scaled down.
    reporting = {2009: 800, 2010: 2000}
    counts = {"correction": (60, 55, 50), "recast": (540, 420, 400), "tag_switch": (200, 160, 150)}
    days = {"correction": "98.0", "recast": "365.0", "tag_switch": "180.0"}
    for metric, scale in (("net_income", 1.0), ("revenue", 0.8), ("operating_cash_flow", 0.7)):
        for year in range(2009, 2027):
            part = scale * (0.5 if year == 2026 else 1.0)
            for kind, (restated, companies, first_kind) in counts.items():
                out["export_restatements_by_year"].append(
                    {
                        "change_year": year,
                        "restatement_kind": kind,
                        "metric": metric,
                        "restatements": round(restated * part),
                        "companies": round(companies * part),
                        "reporting_companies": reporting.get(year, 4000),
                        "median_abs_restatement_pct": 0.05,
                        "median_days_to_first_change": decimal.Decimal(days[kind]),
                        "companies_by_first_kind": round(first_kind * part),
                        "restatement_group_key": f"{year}|{kind}|{metric}",
                    }
                )

    # The largest restatements: Fixture Co 01 to 10 amended net income (Co 01 is in both lists),
    # Co 11 to 20 changed revenue in a later filing, Co 21 to 25 made small amendments that rank
    # by their share of assets, and one company the screener does not cover (a link to EDGAR).
    def restatement(n, cik, name, metric, kind, form, changed, amount, assets, selected_by):
        first = 1e8 * max(n, 1)
        return {
            "restatement_key": f"r{n}",
            "cik": cik,
            "company_name": name,
            "metric": metric,
            "period_end": dt.date(changed.year - 1, 12, 31),
            "duration_quarters": 4,
            "restatement_kind": kind,
            "first_change_form": form,
            "first_reported_at": ntz(changed.year, 2, 20, 16),
            "first_change_at": changed,
            "days_to_first_change": (changed - ntz(changed.year, 2, 20, 16)).days,
            "first_reported_value": money(first),
            "latest_value": money(first + amount),
            "restatement_amount": money(amount),
            "restatement_pct": round(amount / first, 6),
            "total_assets": money(assets),
            "change_to_assets": round(abs(amount) / assets, 6),
            "selected_by": selected_by,
        }

    largest = out["export_restatements_largest"]
    for n in range(1, 11):
        largest.append(
            restatement(
                n,
                1_000_000 + n,
                f"Fixture Co {n:02d}",
                "net_income",
                "correction",
                "10-K/A",
                ntz(2025, 6, 2, 9),
                -1e7 * (21 - n),
                1e9 * n,
                "both" if n == 1 else "amount",
            )
        )
    for n in range(11, 21):
        largest.append(
            restatement(
                n,
                1_000_000 + n,
                f"Fixture Co {n:02d}",
                "revenue",
                "recast",
                "10-K",
                ntz(2024, 3, 1, 9),
                5e6 * (21 - n),
                1e9 * n,
                "amount",
            )
        )
    for n in range(21, 26):
        largest.append(
            restatement(
                n,
                1_000_000 + n,
                f"Fixture Co {n:02d}",
                "net_income",
                "correction",
                "10-Q/A",
                ntz(2025, 9, 15, 9),
                -2e6,
                5e6,
                "share_of_assets",
            )
        )
    largest.append(
        restatement(
            26,
            2_000_001,
            "Gone Co",
            "operating_cash_flow",
            "recast",
            "10-K",
            ntz(2023, 3, 1, 9),
            3e8,
            4e9,
            "amount",
        )
    )
    # Filing timeliness, in round numbers the site's tests can check. 10-Ks for 2025: 98% of
    # large accelerated filers' on time, 92% of accelerated, 76% of non-accelerated (3,040 of
    # 4,000; of the other 960, 576 within a notice's extension and 384 late). Notices are known
    # from 2025, so earlier years count every filing not on time as late. 2026 is to date:
    # half the filings, and more of them on time. Fewer smaller companies before 2011 (XBRL's
    # phase-in).
    timeliness = {
        # group: (filings, on-time share, deadline, median days, p90 days, median days late)
        "10-K": {
            "large_accelerated": (1500, 0.98, 60, "55.0", "59.0", "6.0"),
            "accelerated": (1200, 0.92, 75, "70.0", "74.0", "8.0"),
            "non_accelerated": (4000, 0.76, 90, "86.0", "104.0", "12.0"),
        },
        "10-Q": {
            "large_accelerated": (4500, 0.99, 40, "36.0", "39.0", "3.0"),
            "accelerated": (3600, 0.95, 40, "38.0", "40.0", "4.0"),
            "non_accelerated": (12000, 0.85, 45, "43.0", "48.0", "6.0"),
        },
    }
    phase_in = {2009: {"accelerated": 0.3, "non_accelerated": 0.05}, 2010: {"non_accelerated": 0.3}}
    for form, groups in timeliness.items():
        for group, (base, share, deadline, median, p90, late_by) in groups.items():
            for year in range(2009, 2027):
                filings = round(base * phase_in.get(year, {}).get(group, 1.0))
                if year == 2026:
                    filings, share_now = filings // 2, min(share + 0.01, 1.0)
                else:
                    share_now = share
                on_time = round(filings * share_now)
                not_on_time = filings - on_time
                notices = year >= 2025
                within = round(not_on_time * 0.6) if notices else 0
                late = not_on_time - within
                out["export_filing_timeliness"].append(
                    {
                        "filer_group": group,
                        "form": form,
                        "period_year": year,
                        "filings": filings,
                        "on_time_filings": on_time,
                        "within_extension_filings": within,
                        "late_filings": late,
                        "late_notices": within + round(late * 0.1) if notices else 0,
                        "notice_data_available": notices,
                        "deadline_days": deadline,
                        "extension_days": 15 if form == "10-K" else 5,
                        "median_days_to_file": decimal.Decimal(median),
                        "p90_days_to_file": decimal.Decimal(p90),
                        "median_days_past_due_when_late": decimal.Decimal(late_by),
                        "on_time_share": on_time / filings,
                        "timeliness_key": f"{group}|{form}|{year}",
                    }
                )
    # Every day state appears: the first three days before the record began, weekends' mornings
    # with no run expected, one each held (with a drill), late, failed and missed, the rest met.
    special = {9: "held", 14: "late", 16: "failed", 22: "missed"}
    for d in range(30):
        day = dt.date(2026, 10, 20) + dt.timedelta(days=d)
        expected = (day - dt.timedelta(days=1)).weekday() < 5
        ran = expected  # a morning runs when the day before was a business day
        state = (
            "no_run_expected"
            if not expected
            else "not_recorded"
            if d < 3
            else special.get(d, "met")
        )
        exported = {
            "met": ntz(day.year, day.month, day.day, 6, 8),
            "held": ntz(day.year, day.month, day.day, 13, 57),
            "late": ntz(day.year, day.month, day.day, 11, 40),
        }.get(state)
        out["export_pipeline_health"].append(
            {
                "run_expected": expected,
                "first_exported_at": exported,
                "exported_by_target": state == "met",
                "has_failed_check": state == "held",
                "has_failed_task": state in ("held", "failed"),
                "has_drill": state == "held",
                "day_state": state,
                "date_day": day,
                "latest_index_day": day - dt.timedelta(days=1) if ran else None,
                "index_lag_days": 1 if ran else None,
                "dbt_invocations": 2 if ran else 0,
                "tests_run": 980 if ran else 0,
                "tests_passed": (973 if state == "held" else 974) if ran else 0,
                "tests_warned": 6 if ran else 0,
                "tests_failed": 1 if state == "held" else 0,
                "models_failed": 0,
                "test_pass_rate": (1 - 1 / 980 if state == "held" else 1.0) if ran else None,
                "volume_checks": 3 if ran else 0,
                "volume_failures": 0,
                "dollars": decimal.Decimal("0.041300") if ran else decimal.Decimal("0"),
            }
        )
    return out


def described(path: Path) -> dict:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def is_fixture(folder: Path) -> bool:
    try:
        return json.loads((folder / "site.json").read_text()).get("run_id") == "fixture"
    except (OSError, ValueError):
        return False


def write(out_dir: Path) -> dict[str, int]:
    """A fresh fixture in out_dir, replacing an earlier fixture (and any app added to it)."""
    if out_dir.exists():
        if any(out_dir.iterdir()) and not is_fixture(out_dir):
            raise SystemExit(f"{out_dir} is not empty and not a fixture: not replacing it")
        shutil.rmtree(out_dir)
    # Seeded, so the fixture is identical every time; invented numbers, not a secret.
    shapes, data = contract(), rows(random.Random(20261119))  # noqa: S311
    (out_dir / "data").mkdir(parents=True)
    (out_dir / "dbt-docs").mkdir()
    (out_dir / "dbt-docs" / "index.html").write_text(
        "<!doctype html>\n<title>dbt docs (fixture)</title>\n<p>The dbt docs stand-in.</p>\n"
    )
    counts = {}
    for name, columns in shapes.items():
        schema = pa.schema(columns)
        table = pa.Table.from_pylist(
            [{c: r.get(c) for c, _ in columns} for r in data[name]], schema=schema
        )
        pq.write_table(table, out_dir / "data" / f"{name}.parquet", compression="zstd")
        counts[name] = table.num_rows
    # As build_site.py writes it: each file's bytes and sha256 (the SQL page checks every table
    # it downloads against them), and the rows of each table.
    files = {"dbt-docs.html": described(out_dir / "dbt-docs" / "index.html")}
    for name, count in counts.items():
        files[f"{name}.parquet"] = {
            **described(out_dir / "data" / f"{name}.parquet"),
            "rows": count,
        }
    site = {
        "run_id": "fixture",
        "exported_at": "2026-11-19T06:05:21+00:00",
        "commit": "0" * 12,
        "folder": "exports/site/runs/fixture",
        "files": files,
    }
    (out_dir / "site.json").write_text(json.dumps(site, indent=2) + "\n")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the site's fixture export.")
    parser.add_argument("--out", type=Path, default=Path("site/fixture"))
    args = parser.parse_args()
    for name, n in write(args.out).items():
        print(f"{name}: {n} rows")


if __name__ == "__main__":
    main()
