"""Unit tests for SecClient.metadata: a file's size and date from a HEAD request."""

from __future__ import annotations

import responses

from earningswatch.sec_client import SecClient

URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/2026q3.zip"


def _client() -> SecClient:
    return SecClient("EarningsWatch test@example.com", rate_per_second=1000)


@responses.activate
def test_metadata_reads_size_and_date() -> None:
    responses.add(
        responses.HEAD,
        URL,
        headers={"Content-Length": "65148008", "Last-Modified": "Thu, 01 Oct 2026 12:00:00 GMT"},
    )

    remote = _client().metadata(URL)

    assert remote is not None
    assert remote.size_bytes == 65148008
    assert remote.last_modified == "Thu, 01 Oct 2026 12:00:00 GMT"


@responses.activate
def test_metadata_is_none_when_the_file_does_not_exist() -> None:
    responses.add(responses.HEAD, URL, status=404)

    assert _client().metadata(URL) is None


@responses.activate
def test_compressed_transfer_size_is_not_trusted() -> None:
    # With gzip on the wire, Content-Length is the compressed size, not the file's size.
    responses.add(
        responses.HEAD, URL, headers={"Content-Length": "1000", "Content-Encoding": "gzip"}
    )

    remote = _client().metadata(URL)

    assert remote is not None
    assert remote.size_bytes is None
