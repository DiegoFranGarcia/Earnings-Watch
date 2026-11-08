"""Guards on the dbt project's documentation, checked by parsing it (no warehouse needed).

Every model must state its grain, and every model in the marts must enforce a contract, so
these rules cannot quietly erode as models are added.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
dbt_runner = pytest.importorskip("dbt.cli.main")


@pytest.fixture(scope="module")
def manifest(tmp_path_factory):
    target = tmp_path_factory.mktemp("dbt_target")
    result = dbt_runner.dbtRunner().invoke(
        [
            "parse",
            "--project-dir",
            str(ROOT / "dbt"),
            "--profiles-dir",
            str(ROOT / "dbt"),
            "--target-path",
            str(target),
            "--quiet",
        ]  # fmt: skip
    )
    assert result.success, result.exception
    return result.result


def _models(manifest):
    return [node for node in manifest.nodes.values() if node.resource_type == "model"]


def test_every_model_states_its_grain(manifest) -> None:
    missing = [model.name for model in _models(manifest) if "Grain:" not in model.description]
    assert not missing, f"models without 'Grain:' in their description: {missing}"


def test_every_mart_model_enforces_a_contract(manifest) -> None:
    unenforced = [
        model.name
        for model in _models(manifest)
        if model.fqn[1] == "marts" and not model.config.contract.enforced
    ]
    assert not unenforced, f"mart models without an enforced contract: {unenforced}"
