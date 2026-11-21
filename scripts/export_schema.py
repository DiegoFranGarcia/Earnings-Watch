"""Write the site's copy of the export contract: each exported table, its columns, their types
and descriptions, as JSON the SQL page shows beside its editor.

dbt/models/exports/_exports.yml is the only source; this file is derived from it and committed,
and a test fails when the two disagree, so a renamed column or a new description reaches the
page in the same pull request. Run it after changing _exports.yml:

    uv run python scripts/export_schema.py
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "dbt" / "models" / "exports" / "_exports.yml"
OUT = ROOT / "site" / "src" / "lib" / "generated" / "exports.json"


def _text(value) -> str | None:
    """A description as one plain line (YAML's folded text keeps a trailing newline)."""
    return " ".join(str(value).split()) if value else None


def schema(contract: dict) -> list[dict]:
    """The exported tables in the contract's order: each column's name, type and description."""
    return [
        {
            "name": model["name"],
            "description": _text(model.get("description")),
            "columns": [
                {
                    "name": column["name"],
                    "type": column["data_type"],
                    "description": _text(column.get("description")),
                }
                for column in model["columns"]
            ],
        }
        for model in contract["models"]
        if model["name"].startswith("export_")
    ]


def render(contract_path: Path = CONTRACT) -> str:
    tables = schema(yaml.safe_load(contract_path.read_text()))
    document = {"source": "dbt/models/exports/_exports.yml", "tables": tables}
    return json.dumps(document, indent=1) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(ROOT)}")
