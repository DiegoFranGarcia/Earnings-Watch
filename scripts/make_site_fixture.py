"""Write a small, invented export in the shape of the real one, for building and testing the site.

The site's CI check (`site`) builds the app against this, never against real data. Every table
has exactly the columns and types its dbt contract declares (dbt/models/exports/_exports.yml),
so a contract change that the site has not caught up with fails the build, not the live site.
Company names are invented ("Fixture Co 01") so nothing here can be mistaken for real figures.

    uv run python scripts/make_site_fixture.py --out site/fixture
"""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import json
import random
import re
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


def rows(rng: random.Random) -> dict[str, list[dict]]:
    """Invented rows for every table: 40 companies, 12 quarters each."""
    # Twelve calendar quarter ends, 2023-12-31 to 2026-09-30.
    quarter_ends = [quarter_end(2023, 4 + q) for q in range(12)]
    out: dict[str, list[dict]] = {name: [] for name in contract()}
    for i in range(1, 41):
        cik = 1_000_000 + i
        name, group, filer = f"Fixture Co {i:02d}", GROUPS[i % len(GROUPS)], FILERS[i % len(FILERS)]
        flagged = i % 4 == 0
        base_income = rng.uniform(5e6, 4e8)
        for q, end in enumerate(quarter_ends):
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
        for view in VIEWS:
            ttm = base_income * 4.6
            flag_here = flagged and not (
                view == "latest" and i == 8
            )  # one flag gone after a restatement
            out["export_screener"].append(
                {
                    "cik": cik,
                    "reporting_view": view,
                    "period_end": quarter_ends[-1],
                    "fiscal_year": quarter_ends[-1].year,
                    "fiscal_quarter": 3,
                    "known_at": ntz(2026, 11, 2, 21, 15),
                    "sic": 3674,
                    "industry_title": "SEMICONDUCTORS",
                    "filer_status": "1-LAF",
                    "ttm_net_income": money(ttm),
                    "prior_ttm_net_income": money(ttm * 0.78),
                    "ttm_operating_cash_flow": money(ttm * (0.45 if flagged else 1.05)),
                    "prior_ttm_operating_cash_flow": money(ttm * (0.52 if flagged else 0.98)),
                    "average_total_assets": money(ttm * 3.5),
                    "accruals": money(ttm * 0.55),
                    "accruals_to_assets": round(0.11 + i / 400, 4)
                    if flag_here
                    else round(0.02 + i / 1000, 4),
                    "is_flagged": flag_here,
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
    for year in range(2009, 2027):
        for kind in ("tag_switch", "correction", "recast"):
            for metric in ("net_income", "revenue"):
                out["export_restatements_by_year"].append(
                    {
                        "change_year": year,
                        "restatement_kind": kind,
                        "metric": metric,
                        "restatements": rng.randint(50, 900),
                        "companies": rng.randint(20, 400),
                        "median_abs_restatement_pct": round(rng.uniform(0.01, 0.3), 4),
                        "median_days_to_first_change": decimal.Decimal(
                            f"{rng.uniform(60, 400):.1f}"
                        ),
                        "restatement_group_key": f"{year}|{kind}|{metric}",
                    }
                )
    for n in range(1, 21):
        out["export_restatements_largest"].append(
            {
                "restatement_key": f"r{n}",
                "cik": 1_000_000 + n,
                "company_name": f"Fixture Co {n:02d}",
                "metric": "net_income",
                "period_end": dt.date(2024, 12, 31),
                "duration_quarters": 4,
                "restatement_kind": "correction",
                "first_change_form": "10-K/A",
                "first_reported_at": ntz(2025, 2, 20, 16),
                "first_change_at": ntz(2025, 6, 2, 9),
                "days_to_first_change": 102,
                "first_reported_value": money(1e8 * n),
                "latest_value": money(9e7 * n),
                "restatement_amount": money(-1e7 * n),
                "restatement_pct": -0.1,
            }
        )
    for year in range(2015, 2026):
        for status, group in (("1-LAF", "large_accelerated"), ("4-NON", "non_accelerated")):
            for form in ("10-K", "10-Q"):
                filings = rng.randint(800, 6000)
                late = rng.randint(5, 300)
                out["export_filing_timeliness"].append(
                    {
                        "timeliness_key": f"{status}|{form}|{year}",
                        "filer_status": status,
                        "filer_group": group,
                        "form": form,
                        "period_year": year,
                        "filings": filings,
                        "on_time_filings": filings - late,
                        "within_extension_filings": late // 2,
                        "late_filings": late - late // 2,
                        "late_notices": late // 3,
                        "median_days_to_file": 38,
                        "p90_days_to_file": 61,
                        "median_days_past_due_when_late": 9,
                        "notice_data_available": year >= 2025,
                        "on_time_share": round(1 - late / filings, 4),
                    }
                )
    for d in range(30):
        day = dt.date(2026, 10, 20) + dt.timedelta(days=d)
        ran = day.weekday() < 6
        out["export_pipeline_health"].append(
            {
                "date_day": day,
                "latest_index_day": day - dt.timedelta(days=1) if ran else None,
                "index_lag_days": 1 if ran else None,
                "dbt_invocations": 2 if ran else 0,
                "tests_run": 980 if ran else 0,
                "tests_passed": 974 if ran else 0,
                "tests_warned": 6 if ran else 0,
                "tests_failed": 0,
                "models_failed": 0,
                "test_pass_rate": 1.0 if ran else None,
                "volume_checks": 3 if ran else 0,
                "volume_failures": 0,
                "dollars": decimal.Decimal("0.041300") if ran else decimal.Decimal("0"),
            }
        )
    return out


def write(out_dir: Path) -> dict[str, int]:
    # Seeded, so the fixture is identical every time; invented numbers, not a secret.
    shapes, data = contract(), rows(random.Random(20261119))  # noqa: S311
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, columns in shapes.items():
        schema = pa.schema(columns)
        table = pa.Table.from_pylist(
            [{c: r.get(c) for c, _ in columns} for r in data[name]], schema=schema
        )
        pq.write_table(table, out_dir / "data" / f"{name}.parquet", compression="zstd")
        counts[name] = table.num_rows
    site = {
        "run_id": "fixture",
        "exported_at": "2026-11-19T06:05:21+00:00",
        "commit": "0" * 12,
        "folder": "exports/site/runs/fixture",
        "files": {f"{n}.parquet": {"rows": c} for n, c in counts.items()},
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
