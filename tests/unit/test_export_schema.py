"""The SQL page's copy of the export contract is exactly what scripts/export_schema.py writes."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "export_schema", ROOT / "scripts" / "export_schema.py"
)
export_schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_schema)


def test_the_committed_schema_matches_the_contract() -> None:
    assert export_schema.OUT.read_text() == export_schema.render(), (
        "site/src/lib/generated/exports.json is out of date: "
        "run uv run python scripts/export_schema.py"
    )


def test_every_exported_table_and_column_is_there_with_its_type() -> None:
    tables = {t["name"]: t for t in json.loads(export_schema.OUT.read_text())["tables"]}
    assert len(tables) == 7
    screener = {c["name"]: c for c in tables["export_screener"]["columns"]}
    assert screener["accruals_to_assets"]["type"] == "double"
    assert all(c["type"] for t in tables.values() for c in t["columns"])
    assert tables["export_screener"]["description"].startswith("Grain:")
