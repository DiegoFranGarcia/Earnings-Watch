"""The site's fixture export keeps the shape of the real one: the dbt export contract.

If an export model's columns or types change, the fixture changes with them (it is generated from
the contract), and these tests say which side moved: the contract, or publish_site's list.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml

from earningswatch import site_export

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "make_site_fixture", ROOT / "scripts" / "make_site_fixture.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def test_the_fixture_has_every_export_with_exactly_its_contracts_columns_and_types(
    tmp_path,
) -> None:
    counts = fixture.write(tmp_path)
    contract = yaml.safe_load(fixture.CONTRACT.read_text())["models"]
    assert set(counts) == {m["name"] for m in contract}
    for model in contract:
        schema = pq.read_schema(tmp_path / "data" / f"{model['name']}.parquet")
        assert schema.names == [c["name"] for c in model["columns"]], model["name"]
        for column in model["columns"]:
            assert schema.field(column["name"]).type == fixture.arrow_type(column["data_type"]), (
                f"{model['name']}.{column['name']}"
            )
        assert counts[model["name"]] > 0


def test_publish_site_exports_exactly_the_contracts_models() -> None:
    contract = yaml.safe_load(fixture.CONTRACT.read_text())["models"]
    assert set(site_export.EXPORT_MODELS) == {m["name"] for m in contract}


def test_the_fixture_is_the_same_every_time(tmp_path) -> None:
    fixture.write(tmp_path / "a")
    fixture.write(tmp_path / "b")
    for path in sorted((tmp_path / "a" / "data").iterdir()):
        assert pq.read_table(path).equals(pq.read_table(tmp_path / "b" / "data" / path.name)), (
            path.name
        )


def test_the_fixture_is_laid_out_as_build_site_lays_out_an_export(tmp_path) -> None:
    fixture.write(tmp_path / "f")
    assert (tmp_path / "f" / "dbt-docs" / "index.html").is_file()
    assert (tmp_path / "f" / "site.json").is_file()


def test_a_fixture_replaces_an_earlier_one_but_nothing_else(tmp_path) -> None:
    fixture.write(tmp_path / "f")
    (tmp_path / "f" / "index.html").write_text("an app added earlier")
    fixture.write(tmp_path / "f")
    assert not (tmp_path / "f" / "index.html").exists()
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "notes.txt").write_text("mine")
    with pytest.raises(SystemExit, match="not a fixture"):
        fixture.write(tmp_path / "other")
    assert (tmp_path / "other" / "notes.txt").read_text() == "mine"
