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
TABLE = b"PAR1 stand-in"


def entry(name: str, body: bytes, **extra) -> dict:
    return {
        "name": name,
        "key": f"{FOLDER}/{name}",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        **extra,
    }


def manifest(**changes) -> dict:
    """A complete export: the dbt docs first, then every table the site requires."""
    data = {
        "schema": 1,
        "run_id": "asset_triggered__2026-11-19T06:01:02+00:00",
        "exported_at": "2026-11-19T06:30:00+00:00",
        "release": "123456789012.dkr.ecr.us-east-1.amazonaws.com/earnings-watch-dev/airflow:"
        "01be28d66ebc",
        "folder": FOLDER,
        "files": [
            entry("dbt-docs.html", DOCS),
            *(entry(f"{t}.parquet", TABLE, rows=100 + i) for i, t in enumerate(build_site.TABLES)),
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
            **{f"{FOLDER}/{t}.parquet": TABLE for t in build_site.TABLES},
        }
    )


def test_lays_out_the_latest_export(tmp_path) -> None:
    bucket = bucket_with(manifest())
    out = tmp_path / "_site"
    build_site.build("b", "", out, download=bucket)

    assert bucket.keys[:2] == [build_site.POINTER_KEY, f"{FOLDER}/dbt-docs.html"]
    assert len(bucket.keys) == 2 + len(build_site.TABLES)
    assert (out / "dbt-docs" / "index.html").read_bytes() == DOCS
    live = json.loads((out / "site.json").read_text())
    assert live["folder"] == FOLDER
    assert live["commit"] == "01be28d66ebc"
    assert live["exported_at"] == "2026-11-19T06:30:00+00:00"
    assert live["files"]["export_screener.parquet"]["rows"] == 100
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == sorted(
        ["dbt-docs/index.html", "site.json", *(f"data/{t}.parquet" for t in build_site.TABLES)]
    )


def test_the_export_has_no_front_page_of_its_own(tmp_path) -> None:
    # The app's build provides index.html (--add-app); the export never writes one.
    out = tmp_path / "_site"
    build_site.build("b", "", out, download=bucket_with(manifest()))
    assert not (out / "index.html").exists()


def test_the_account_id_in_the_release_never_reaches_the_site(tmp_path) -> None:
    out = tmp_path / "_site"
    build_site.build("b", "", out, download=bucket_with(manifest()))
    for path in out.rglob("*"):
        if path.is_file():
            assert "123456789012" not in path.read_text(), path


def test_a_named_export_rolls_back_to_that_run(tmp_path) -> None:
    bucket = bucket_with(manifest())
    build_site.build("b", FOLDER, tmp_path / "_site", download=bucket)
    assert bucket.keys[0] == f"{FOLDER}/manifest.json"


@pytest.mark.parametrize(
    "export", ["exports/site/runs/../current.json", "exports/site/runs/a/b", "s3://x", "runs/x"]
)
def test_an_export_outside_the_runs_folder_is_refused(tmp_path, export) -> None:
    with pytest.raises(build_site.BadExport, match="not an export folder"):
        build_site.build("b", export, tmp_path / "_site", download=bucket_with(manifest()))


def test_a_named_export_must_describe_itself(tmp_path) -> None:
    other = "exports/site/runs/other"
    bucket = bucket_with(manifest())
    bucket.objects[f"{other}/manifest.json"] = json.dumps(manifest()).encode()
    with pytest.raises(build_site.BadExport, match="describes"):
        build_site.build("b", other, tmp_path / "_site", download=bucket)


def test_a_file_that_does_not_match_its_manifest_stops_the_build(tmp_path) -> None:
    bucket = bucket_with(manifest(), docs=b"<html>altered</html>")
    with pytest.raises(build_site.BadExport, match="does not match its manifest"):
        build_site.build("b", "", tmp_path / "_site", download=bucket)


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
        build_site.build("b", "", tmp_path / "_site", download=bucket)
    assert bucket.keys == [build_site.POINTER_KEY]


def test_a_manifest_listing_a_file_twice_is_refused(tmp_path) -> None:
    data = manifest()
    data["files"].append(copy.deepcopy(data["files"][0]))
    with pytest.raises(build_site.BadExport, match="twice"):
        build_site.build("b", "", tmp_path / "_site", download=bucket_with(data))


def test_a_release_without_a_commit_records_none(tmp_path) -> None:
    out = tmp_path / "_site"
    build_site.build("b", "", out, download=bucket_with(manifest(release="not-a-commit")))
    assert json.loads((out / "site.json").read_text())["commit"] is None


@pytest.mark.parametrize("missing", ["dbt-docs.html", "export_screener.parquet"])
def test_an_export_missing_a_required_file_is_refused(tmp_path, missing) -> None:
    data = manifest()
    data["files"] = [e for e in data["files"] if e["name"] != missing]
    with pytest.raises(build_site.BadExport, match=f"missing {missing}"):
        build_site.build("b", "", tmp_path / "_site", download=bucket_with(data))


def test_an_existing_output_folder_is_never_reused(tmp_path) -> None:
    (tmp_path / "_site").mkdir()
    with pytest.raises(FileExistsError):
        build_site.build("b", "", tmp_path / "_site", download=bucket_with(manifest()))


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


def test_tables_are_laid_out_under_data(tmp_path) -> None:
    out = tmp_path / "_site"
    build_site.build("b", "", out, download=bucket_with(manifest()))
    for table in build_site.TABLES:
        assert (out / "data" / f"{table}.parquet").read_bytes() == TABLE


@pytest.mark.parametrize("rows", [None, 0, "6925"])
def test_a_table_without_a_positive_row_count_is_refused(tmp_path, rows) -> None:
    data = manifest()
    screener = next(e for e in data["files"] if e["name"] == "export_screener.parquet")
    del screener["rows"]
    if rows is not None:
        screener["rows"] = rows
    with pytest.raises(build_site.BadExport, match="row count"):
        build_site.build("b", "", tmp_path / "_site", download=bucket_with(data))


# -- The app beside the export (--add-app) -----------------------------------------------------


def laid_out(tmp_path) -> Path:
    out = tmp_path / "_site"
    build_site.build("b", "", out, download=bucket_with(manifest()))
    return out


def app_build(tmp_path, files: dict[str, str] | None = None, name: str = "build") -> Path:
    app = tmp_path / name
    for rel, text in (
        files
        or {
            "index.html": "<!doctype html>overview",
            "screener/index.html": "<!doctype html>screener",
            "_app/immutable/entry/start.js": "export {}",
        }
    ).items():
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_text(text)
    return app


def test_the_app_goes_beside_the_export_and_changes_none_of_it(tmp_path) -> None:
    out = laid_out(tmp_path)
    before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert build_site.add_app(app_build(tmp_path), out) == 3
    assert (out / "index.html").read_text() == "<!doctype html>overview"
    assert (out / "screener" / "index.html").is_file()
    assert (out / "_app" / "immutable" / "entry" / "start.js").is_file()
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize(
    "rel", ["site.json", "data/export_screener.parquet", "dbt-docs/index.html", "data/new.js"]
)
def test_the_app_may_not_use_the_exports_places(tmp_path, rel) -> None:
    out = laid_out(tmp_path)
    app = app_build(tmp_path, {"index.html": "x", rel: "from the app"})
    with pytest.raises(build_site.BadExport, match="would replace"):
        build_site.add_app(app, out)
    assert not (out / "index.html").exists()  # checked before anything is copied


def test_the_app_is_added_only_once(tmp_path) -> None:
    out = laid_out(tmp_path)
    build_site.add_app(app_build(tmp_path), out)
    with pytest.raises(build_site.BadExport, match="would replace the export's"):
        build_site.add_app(app_build(tmp_path, name="again"), out)


def test_the_app_needs_an_export_and_a_front_page(tmp_path) -> None:
    with pytest.raises(build_site.BadExport, match="holds no export"):
        build_site.add_app(app_build(tmp_path), tmp_path / "empty")
    out = laid_out(tmp_path)
    with pytest.raises(build_site.BadExport, match="no index.html"):
        build_site.add_app(app_build(tmp_path, {"other.html": "x"}, name="bare"), out)


def test_the_app_may_hold_only_plain_files(tmp_path) -> None:
    out = laid_out(tmp_path)
    app = app_build(tmp_path)
    (app / "link.txt").symlink_to(out / "site.json")
    with pytest.raises(build_site.BadExport, match="other than a file"):
        build_site.add_app(app, out)


def test_main_adds_the_app_or_reports_why_not(tmp_path, capsys) -> None:
    out = laid_out(tmp_path)
    app = app_build(tmp_path)
    assert build_site.main(["--add-app", str(app), "--out", str(out)]) == 0
    assert "Added the app's 3 files" in capsys.readouterr().out
    assert build_site.main(["--add-app", str(app), "--out", str(out)]) == 1
    assert "NOT DEPLOYED: the app's build would replace" in capsys.readouterr().err


def test_main_needs_a_bucket_to_build_from_an_export(tmp_path) -> None:
    with pytest.raises(SystemExit):
        build_site.main(["--out", str(tmp_path / "_site")])
