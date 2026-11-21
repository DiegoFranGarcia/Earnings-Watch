"""verify_live_site.py against a local server that answers like GitHub Pages (gzip when offered,
the query string ignored), serving a copy of a deployed site that each test can change."""

from __future__ import annotations

import gzip
import hashlib
import http.server
import importlib.util
import json
import shutil
import sys
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_live_site.py"
spec = importlib.util.spec_from_file_location("verify_live_site", SCRIPT)
verify_live_site = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verify_live_site  # its dataclass looks its module up by name
spec.loader.exec_module(verify_live_site)

BASE = "/Earnings-Watch/"


def described(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def deployed_site(root: Path, run_id: str = "asset_triggered__2026-11-21T13:58:12+00:00_x") -> Path:
    """A small deployed site: two tables, DuckDB's three files, the SQL page and site.json."""
    files = {
        "data/export_a.parquet": b"PAR1" + bytes(range(256)) * 40 + b"PAR1",
        "data/export_b.parquet": b"PAR1" + b"b" * 5000 + b"PAR1",
        "_app/immutable/assets/duckdb-eh.Ab1-x.wasm": b"\0asm" + bytes(range(256)) * 4000,
        "_app/immutable/assets/duckdb-browser-eh.worker.Cd2-y.js": b"self.onmessage=()=>{};" * 500,
        "duckdb/v1.4.3/wasm_eh/parquet.duckdb_extension.wasm": b"\0asm" + b"x" * 3000,
        "dbt-docs/index.html": b"<title>docs</title>",
    }
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    site = {
        "run_id": run_id,
        "files": {
            "dbt-docs.html": described(files["dbt-docs/index.html"]),
            **{Path(r).name: described(d) for r, d in files.items() if r.startswith("data/")},
        },
    }
    (root / "site.json").write_text(json.dumps(site))
    # The label must be what Pages sends for the SQL page's files (gzip, as in serve()).
    sent = sum(len(gzip.compress(d)) for r, d in files.items() if not r.startswith("dbt-docs"))
    (root / "sql").mkdir()
    (root / "sql" / "index.html").write_text(
        f"<button>downloads about {round(sent / 1e6)} MB</button>"
    )
    return root


def serve(live: Path, encoding: str = "gzip"):
    """Serve `live` under BASE like Pages; returns (base URL, server)."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            file = live / path.removeprefix(BASE)
            if not path.startswith(BASE) or not file.is_file():
                self.send_response(404)
                self.end_headers()
                return
            body = file.read_bytes()
            offered = "gzip" in self.headers.get("Accept-Encoding", "")
            self.send_response(200)
            if offered and encoding == "gzip":
                body = gzip.compress(body)
                self.send_header("Content-Encoding", "gzip")
            elif offered and encoding != "identity":
                self.send_header("Content-Encoding", encoding)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}{BASE}", server


@pytest.fixture
def site(tmp_path):
    deployed = deployed_site(tmp_path / "deployed")
    live = tmp_path / "live"
    shutil.copytree(deployed, live)
    return deployed, live


def run(deployed: Path, live: Path, encoding: str = "gzip", timeout: float = 5):
    base, server = serve(live, encoding)
    try:
        return verify_live_site.check(deployed, base, timeout=timeout, interval=0.2)
    finally:
        server.shutdown()


def test_a_live_site_serving_exactly_the_deploy_passes(site) -> None:
    problems, rows = run(*site)
    assert problems == []
    assert sum("| 200 | gzip |" in r for r in rows) == 5  # two tables, DuckDB's three files


def test_the_tables_are_fetched_whole_at_the_sql_pages_address(site) -> None:
    deployed, live = site
    asked = []
    real = verify_live_site.fetch
    base, server = serve(live)
    try:
        verify_live_site.check(
            deployed, base, get=lambda url: asked.append(url) or real(url), timeout=5
        )
    finally:
        server.shutdown()
    tables = sorted(u.removeprefix(base) for u in asked if ".parquet" in u)
    v = "asset_triggered__2026-11-21T13%3A58%3A12%2B00%3A00_x"  # encodeURIComponent's encoding
    assert tables == [f"data/export_a.parquet?v={v}", f"data/export_b.parquet?v={v}"]


def test_a_live_site_still_on_the_previous_export_fails_after_waiting(site) -> None:
    deployed, live = site
    old = json.loads((live / "site.json").read_text()) | {"run_id": "the previous export"}
    (live / "site.json").write_text(json.dumps(old))
    problems, _ = run(deployed, live, timeout=0.5)
    assert len(problems) == 1
    assert "'the previous export'" in problems[0]


def test_a_table_that_differs_from_the_deploy_fails(site) -> None:
    deployed, live = site
    (live / "data" / "export_b.parquet").write_bytes(b"PAR1 something else PAR1")
    problems, rows = run(deployed, live)
    assert any("export_b.parquet" in p and "sha256" in p for p in problems)
    assert any("**no**" in r for r in rows)


def test_a_missing_engine_file_fails(site) -> None:
    deployed, live = site
    next((live / "_app" / "immutable" / "assets").glob("duckdb-eh.*.wasm")).unlink()
    problems, _ = run(deployed, live)
    assert any("HTTP 404" in p and "duckdb-eh" in p for p in problems)


def test_an_encoding_this_check_cannot_read_fails_loudly(site) -> None:
    problems, _ = run(*site, encoding="br")
    assert any("br" in p and "extend decoded()" in p for p in problems)


def test_a_label_far_from_what_pages_sends_fails(site) -> None:
    deployed, live = site
    page = deployed / "sql" / "index.html"
    page.write_text("<button>downloads about 40 MB</button>")
    problems, _ = run(deployed, live)
    assert problems == ["the SQL page says about 40 MB, but Pages sent 0.0 MB"]


def test_main_refuses_a_plain_http_address(tmp_path) -> None:
    with pytest.raises(SystemExit):
        verify_live_site.main(["--site-dir", str(tmp_path), "--url", "http://example.com/"])
