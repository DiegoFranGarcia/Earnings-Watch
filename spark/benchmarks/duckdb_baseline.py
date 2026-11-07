"""Benchmark baseline: convert FSDS quarters with the slice's DuckDB converter, on one machine.

It runs the slice's own convert() and write_parquet(), so the baseline is the real converter,
not a rewrite. Unlike the slice script, it never uploads anything: benchmark runs cannot touch
the lake. Peak memory is the whole process's, which is fair here because DuckDB runs in-process.

From the repository root:

    uv run python spark/benchmarks/duckdb_baseline.py --quarters 2024q4..2026q3 \
        --bronze-root data/bench/bronze --silver-root data/bench/silver_duckdb
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "slice"), str(ROOT / "spark"), str(ROOT / "airflow" / "dags")]

import duckdb  # noqa: E402

from fsds_to_parquet import convert, write_parquet  # noqa: E402
from lib.quarters import expand  # noqa: E402


def _expected(folder: Path, name: str) -> int:
    return json.loads((folder / f"{name}.manifest.json").read_text())["line_count"] - 1


def _peak_memory_gb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024**3 if sys.platform == "darwin" else 1024**2)  # bytes on macOS, KB on Linux


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quarters", required=True, help="a list or range, e.g. 2024q4..2026q3")
    parser.add_argument("--bronze-root", required=True, type=Path)
    parser.add_argument("--silver-root", required=True, type=Path)
    args = parser.parse_args(argv)

    quarters = expand(args.quarters)
    total_rows = 0
    started = time.perf_counter()
    for quarter in quarters:
        folder = args.bronze_root / f"quarter={quarter}"
        began = time.perf_counter()
        con = duckdb.connect()
        rec = convert(
            con,
            folder / "sub.txt",
            folder / "num.txt",
            _expected(folder, "sub.txt"),
            _expected(folder, "num.txt"),
        )
        write_parquet(con, args.silver_root, quarter)
        con.close()
        total_rows += rec.num.rows_written
        print(
            f"{quarter:<8} num {rec.num.rows_written:>11,}  dupes {rec.num.duplicates_removed:>3,}"
            f"  conflicts {rec.rows_with_conflicting_values:>4,}"
            f"  {time.perf_counter() - began:>6.1f}s",
            flush=True,
        )
    seconds = time.perf_counter() - started
    print(
        f"\nduckdb: {len(quarters)} quarters, {total_rows:,} numbers in {seconds:.1f}s "
        f"({total_rows / seconds:,.0f} rows/s), peak memory {_peak_memory_gb():.2f} GB"
    )


if __name__ == "__main__":
    main()
