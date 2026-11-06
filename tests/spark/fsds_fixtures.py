"""Tiny FSDS quarters in the real file layout, with every awkward case the real data has."""

from __future__ import annotations

import json
from pathlib import Path

from lib.schemas import NUM_COLUMNS, SUB_COLUMNS

ADSH = "0000002488-26-000123"
OTHER = "0000320193-26-000105"


def sub_row(**overrides: str) -> dict[str, str]:
    row = {
        "adsh": ADSH, "cik": "2488", "name": "ADVANCED MICRO DEVICES INC", "sic": "3674",
        "zipba": "02134", "ein": "941692300", "afs": "1-LAF", "wksi": "0", "fye": "1231",
        "form": "10-Q", "period": "20260630", "fy": "2026", "fp": "Q2", "filed": "20260805",
        "accepted": "2026-08-04 17:40:00.0", "prevrpt": "0", "detail": "1", "nciks": "1",
    }  # fmt: skip
    return row | overrides


def num_row(**overrides: str) -> dict[str, str]:
    row = {
        "adsh": ADSH, "tag": "NetIncomeLoss", "version": "us-gaap/2026", "ddate": "20260630",
        "qtrs": "2", "uom": "USD", "value": "1234000000.0000",
    }  # fmt: skip
    return row | overrides


def write_quarter(folder: Path, subs: list[dict], nums: list[dict], extra_num_lines=()) -> Path:
    """Write sub.txt and num.txt (plus manifests with line counts) the way bronze holds them."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, columns, rows, extra in (
        ("sub.txt", SUB_COLUMNS, subs, ()),
        ("num.txt", NUM_COLUMNS, nums, extra_num_lines),
    ):
        lines = ["\t".join(columns)]
        lines += ["\t".join(row.get(column, "") for column in columns) for row in rows]
        lines += list(extra)
        path = folder / name
        path.write_text("\n".join(lines) + "\n")
        manifest = {"size_bytes": path.stat().st_size, "line_count": len(lines)}
        (folder / f"{name}.manifest.json").write_text(json.dumps(manifest))
    return folder


def awkward_quarter(root: Path) -> Path:
    """One quarter exercising every rule: quotes, duplicates, conflicts, bad values, bad lines."""
    subs = [
        sub_row(),
        sub_row(adsh=OTHER, cik="320193", name='"APPLE\tINC"', sic="3571", fp="FY",
                form="10-K", prevrpt="1", changed="20250115"),
    ]  # fmt: skip
    nums = [
        num_row(),
        num_row(),  # an exact duplicate: removed and counted
        num_row(tag="Assets", qtrs="0", ddate="20260630", value="9000.5000"),
        num_row(tag="Revenues", value="100.0000"),  # these two share a key, different values:
        num_row(tag="Revenues", value="200.0000"),  # both kept, both flagged
        num_row(tag="ProfitLoss", segments='"Fund=Alpha\tBeta;"'),  # a tab inside quotes
        num_row(tag="ProfitLoss", segments="BusinessSegments=DataCenter;"),
        num_row(tag="Liabilities", qtrs="0", value=""),  # no value at all: stays null
        num_row(tag="Goodwill", qtrs="0", value="not a number"),  # a cast failure, counted
        num_row(adsh="0000000000-26-999999", tag="Cash", qtrs="0"),  # no matching filing
        num_row(adsh=OTHER, tag="NetIncomeLoss", qtrs="4", ddate="20260930", coreg="Sub1"),
    ]
    return write_quarter(
        root / "quarter=2026q3", subs, nums, extra_num_lines=["a line\twith too\tfew fields"]
    )
