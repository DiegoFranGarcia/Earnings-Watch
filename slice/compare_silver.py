"""Compare two silver outputs for one quarter: same columns, same types, same rows.

Used to prove the Spark job reproduces the DuckDB converter exactly (the slice's silver
is the reference). Row comparison uses EXCEPT ALL in both directions, so duplicates count.

    uv run python slice/compare_silver.py data/silver data/silver_spark 2026q3
"""

from __future__ import annotations

import argparse
import sys

import duckdb

TABLES = ("sub", "num")


def _relation(con: duckdb.DuckDBPyConnection, root: str, table: str, quarter: str):
    path = f"{root.rstrip('/')}/fsds/{table}/source_quarter={quarter}/*.parquet"
    return con.read_parquet(path)


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    return con.sql(sql).fetchone()[0]


def compare(left_root: str, right_root: str, quarter: str) -> list[str]:
    """Differences between the two outputs; an empty list means identical."""
    con = duckdb.connect()
    problems = []
    for table in TABLES:
        left = _relation(con, left_root, table, quarter)
        right = _relation(con, right_root, table, quarter)
        left_schema = list(zip(left.columns, map(str, left.types), strict=True))
        right_schema = list(zip(right.columns, map(str, right.types), strict=True))
        if left_schema != right_schema:
            for a, b in zip(left_schema, right_schema, strict=False):
                if a != b:
                    problems.append(f"{table}: column {a} vs {b}")
            if len(left_schema) != len(right_schema):
                problems.append(f"{table}: {len(left_schema)} vs {len(right_schema)} columns")
            continue
        con.register("l", left)
        con.register("r", right)
        only_left = _scalar(con, "SELECT count(*) FROM (FROM l EXCEPT ALL FROM r)")
        only_right = _scalar(con, "SELECT count(*) FROM (FROM r EXCEPT ALL FROM l)")
        rows = (left.count("*").fetchone()[0], right.count("*").fetchone()[0])
        if only_left or only_right or rows[0] != rows[1]:
            problems.append(
                f"{table}: {rows[0]:,} vs {rows[1]:,} rows; {only_left:,} only on the left, "
                f"{only_right:,} only on the right"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("left_root")
    parser.add_argument("right_root")
    parser.add_argument("quarter")
    args = parser.parse_args(argv)
    problems = compare(args.left_root, args.right_root, args.quarter)
    for problem in problems:
        print(f"DIFFERENT  {problem}")
    print("IDENTICAL: same columns, same types, same rows" if not problems else "")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
