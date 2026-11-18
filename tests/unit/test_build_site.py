"""Unit tests for building the site from an export. Downloads are faked; no AWS calls."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_site.py"
spec = importlib.util.spec_from_file_location("build_site", SCRIPT)
build_site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_site)

FOLDER = "exports/site/runs/asset_triggered__2026-11-19T06_01_02_00_00"
DOCS = b"<html>the dbt docs</html>"
REPO = "DiegoFranGarcia/Earnings-Watch"


def manifest(**changes) -> dict:
    data = {
        "schema": 1,
        "run_id": "asset_triggered__2026-11-19T06:01:02+00:00",
        "exported_at": "2026-11-19T06:30:00+00:00",
        "release": "123456789012.dkr.ecr.us-east-1.amazonaws.com/earnings-watch-dev/airflow:"
        "01be28d66ebc",
        "folder": FOLDER,
        "files": [
            {
                "name": "dbt-docs.html",
                "key": f"{FOLDER}/dbt-docs.html",
                "bytes": len(DOCS),
                "sha256": hashlib.sha256(DOCS).hexdigest(),
            }
        ],
    }
    data.update(changes)
    return data


class FakeBucket:
    """Serves objects by key, as `aws s3 cp` would, and records what was downloaded."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects, self.keys = objects, []

    def __call__(self, bucket: str, key: str, dest: Path) -> None:
        self.keys.append(key)
        dest.write_bytes(self.objects[key])


def bucket_with(pointer: dict, docs: bytes = DOCS) -> FakeBucket:
    body = json.dumps(pointer).encode()
    return FakeBucket(
        {
            build_site.POINTER_KEY: body,
            f"{FOLDER}/manifest.json": body,
            f"{FOLDER}/dbt-docs.html": docs,
        }
    )


def test_builds_the_site_from_the_latest_export(tmp_path) -> None:
    bucket = bucket_with(manifest())
    out = tmp_path / "_site"
    build_site.build("b", "", out, REPO, download=bucket)

    assert bucket.keys == [build_site.POINTER_KEY, f"{FOLDER}/dbt-docs.html"]
    assert (out / "dbt-docs" / "index.html").read_bytes() == DOCS
    page = (out / "index.html").read_text()
    assert "Thursday 19 November 2026, 06:30 UTC" in page
    assert f"https://github.com/{REPO}/commit/01be28d66ebc" in page
    live = json.loads((out / "site.json").read_text())
    assert live["folder"] == FOLDER
    assert live["commit"] == "01be28d66ebc"
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == [
        "dbt-docs/index.html",
        "index.html",
        "site.json",
    ]


def test_the_account_id_in_the_release_never_reaches_the_site(tmp_path) -> None:
    out = tmp_path / "_site"
    build_site.build("b", "", out, REPO, download=bucket_with(manifest()))
    for path in out.rglob("*"):
        if path.is_file():
            assert "123456789012" not in path.read_text(), path


def test_a_named_export_rolls_back_to_that_run(tmp_path) -> None:
    bucket = bucket_with(manifest())
    build_site.build("b", FOLDER, tmp_path / "_site", REPO, download=bucket)
    assert bucket.keys[0] == f"{FOLDER}/manifest.json"


@pytest.mark.parametrize(
    "export", ["exports/site/runs/../current.json", "exports/site/runs/a/b", "s3://x", "runs/x"]
)
def test_an_export_outside_the_runs_folder_is_refused(tmp_path, export) -> None:
    with pytest.raises(build_site.BadExport, match="not an export folder"):
        build_site.build("b", export, tmp_path / "_site", REPO, download=bucket_with(manifest()))


def test_a_named_export_must_describe_itself(tmp_path) -> None:
    other = "exports/site/runs/other"
    bucket = bucket_with(manifest())
    bucket.objects[f"{other}/manifest.json"] = json.dumps(manifest()).encode()
    with pytest.raises(build_site.BadExport, match="describes"):
        build_site.build("b", other, tmp_path / "_site", REPO, download=bucket)


def test_a_file_that_does_not_match_its_manifest_stops_the_build(tmp_path) -> None:
    bucket = bucket_with(manifest(), docs=b"<html>altered</html>")
    with pytest.raises(build_site.BadExport, match="does not match its manifest"):
        build_site.build("b", "", tmp_path / "_site", REPO, download=bucket)


def bad_entry(**changes) -> dict:
    data = manifest()
    data["files"][0].update(changes)
    return data


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (manifest(schema=2), "schema 1"),
        (manifest(folder="exports/site/current.json"), "not an export folder"),
        (manifest(exported_at="yesterday"), "exported_at"),
        (manifest(files=[]), "no files"),
        (bad_entry(name="../index.html"), "not a plain file name"),
        (bad_entry(name="tracker.js", key=f"{FOLDER}/tracker.js"), "not part of the site"),
        (bad_entry(key="exports/site/runs/other/dbt-docs.html"), "outside the export"),
        (bad_entry(bytes=21 * 1024 * 1024), "budget"),
        (bad_entry(sha256="abc"), "sha256"),
    ],
)
def test_a_manifest_that_is_wrong_is_refused_before_any_download(tmp_path, bad, message):
    bucket = bucket_with(bad)
    with pytest.raises(build_site.BadExport, match=message):
        build_site.build("b", "", tmp_path / "_site", REPO, download=bucket)
    assert bucket.keys == [build_site.POINTER_KEY]


def test_a_manifest_listing_a_file_twice_is_refused(tmp_path) -> None:
    data = manifest()
    data["files"].append(copy.deepcopy(data["files"][0]))
    with pytest.raises(build_site.BadExport, match="twice"):
        build_site.build("b", "", tmp_path / "_site", REPO, download=bucket_with(data))


def test_manifest_values_are_escaped_on_the_page(tmp_path) -> None:
    out = tmp_path / "_site"
    data = manifest(run_id="<script>alert(1)</script>", release="not-a-commit")
    build_site.build("b", "", out, REPO, download=bucket_with(data))
    page = (out / "index.html").read_text()
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "unknown release" in page


def test_an_existing_output_folder_is_never_reused(tmp_path) -> None:
    (tmp_path / "_site").mkdir()
    with pytest.raises(FileExistsError):
        build_site.build("b", "", tmp_path / "_site", REPO, download=bucket_with(manifest()))


def test_the_budget_is_the_same_as_the_exports() -> None:
    # Skipped only until the export (pull request #17) is on main.
    site_export = pytest.importorskip("earningswatch.site_export")
    assert build_site.FILE_BUDGET_BYTES == site_export.FILE_BUDGET_BYTES


def test_main_reports_a_bad_export_without_a_traceback(tmp_path, monkeypatch, capsys) -> None:
    def refuse(*args, **kwargs):
        raise build_site.BadExport("the export is missing dbt-docs.html")

    monkeypatch.setattr(build_site, "build", refuse)
    assert build_site.main(["--bucket", "b", "--out", str(tmp_path / "_site")]) == 1
    assert "NOT DEPLOYED: the export is missing" in capsys.readouterr().err
