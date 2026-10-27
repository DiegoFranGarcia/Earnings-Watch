"""Unit tests for the SEC client. No network: HTTP is faked with `responses`."""

from __future__ import annotations

import hashlib

import pytest
import requests
import responses

from earningswatch.sec_client import (
    SecClient,
    SecForbiddenError,
    SecNotFoundError,
    SecRetriesExhaustedError,
    TokenBucket,
)

URL = "https://www.sec.gov/Archives/edgar/daily-index/index.json"
FILE_URL = "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/master.20261023.idx"
USER_AGENT = "EarningsWatch test@example.com"


class FakeClock:
    """Time that only moves when someone sleeps, so tests never really wait."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(clock: FakeClock) -> SecClient:
    return SecClient(USER_AGENT, max_attempts=3, clock=clock.time, sleep=clock.sleep)


# -- identity -----------------------------------------------------------------


def test_rejects_user_agent_without_email() -> None:
    with pytest.raises(ValueError, match="contact email"):
        SecClient("EarningsWatch")


@responses.activate
def test_sends_declared_headers(client: SecClient) -> None:
    responses.add(responses.GET, URL, json={"ok": True})

    client.get_json(URL)

    sent = responses.calls[0].request.headers
    assert sent["User-Agent"] == USER_AGENT
    assert sent["Accept-Encoding"] == "gzip, deflate"


# -- retries ------------------------------------------------------------------


@responses.activate
def test_retries_server_errors_then_succeeds(client: SecClient, clock: FakeClock) -> None:
    responses.add(responses.GET, URL, status=503)
    responses.add(responses.GET, URL, json={"ok": True})

    assert client.get_json(URL) == {"ok": True}
    assert len(responses.calls) == 2
    assert clock.sleeps, "expected a backoff sleep before the retry"


@responses.activate
def test_429_honours_retry_after(client: SecClient, clock: FakeClock) -> None:
    responses.add(responses.GET, URL, status=429, headers={"Retry-After": "7"})
    responses.add(responses.GET, URL, json={"ok": True})

    client.get_json(URL)

    assert 7.0 in clock.sleeps


@responses.activate
def test_gives_up_after_max_attempts(client: SecClient) -> None:
    responses.add(responses.GET, URL, status=500)

    with pytest.raises(SecRetriesExhaustedError):
        client.get_json(URL)
    assert len(responses.calls) == 3


@responses.activate
def test_retries_connection_errors(client: SecClient) -> None:
    responses.add(responses.GET, URL, body=requests.ConnectionError("network down"))
    responses.add(responses.GET, URL, json={"ok": True})

    assert client.get_json(URL) == {"ok": True}


# -- errors that must not be retried ------------------------------------------


@responses.activate
def test_403_stops_immediately(client: SecClient) -> None:
    responses.add(responses.GET, URL, status=403)

    with pytest.raises(SecForbiddenError):
        client.get_json(URL)
    assert len(responses.calls) == 1, "a 403 must never be retried"


@responses.activate
def test_404_is_reported_not_retried(client: SecClient) -> None:
    responses.add(responses.GET, URL, status=404)

    with pytest.raises(SecNotFoundError):
        client.get_json(URL)
    assert len(responses.calls) == 1


@responses.activate
def test_exists(client: SecClient) -> None:
    responses.add(responses.HEAD, URL, status=200)
    responses.add(responses.HEAD, FILE_URL, status=404)

    assert client.exists(URL) is True
    assert client.exists(FILE_URL) is False


# -- downloads ----------------------------------------------------------------


@responses.activate
def test_download_writes_file_with_checksum(client: SecClient, tmp_path) -> None:
    body = b"CIK|Company Name|Form Type|Date Filed|Filename\n" * 1000
    responses.add(
        responses.GET,
        FILE_URL,
        body=body,
        headers={"Last-Modified": "Fri, 23 Oct 2026 22:15:00 GMT"},
    )

    result = client.download(FILE_URL, tmp_path / "master.idx")

    assert result.path.read_bytes() == body
    assert result.size_bytes == len(body)
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert result.last_modified == "Fri, 23 Oct 2026 22:15:00 GMT"


@responses.activate
def test_download_retries_a_dropped_connection(client: SecClient, tmp_path, monkeypatch) -> None:
    body = b"complete file"
    responses.add(responses.GET, FILE_URL, body=body)

    real_iter_content = requests.Response.iter_content
    calls = {"n": 0}

    def flaky_iter_content(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:  # first attempt: half a file, then the connection drops
            yield b"compl"
            raise requests.exceptions.ChunkedEncodingError("connection dropped")
        yield from real_iter_content(self, *args, **kwargs)

    monkeypatch.setattr(requests.Response, "iter_content", flaky_iter_content)

    result = client.download(FILE_URL, tmp_path / "master.idx")

    assert result.path.read_bytes() == body
    assert result.sha256 == hashlib.sha256(body).hexdigest()


@responses.activate
def test_download_leaves_no_partial_file_when_it_gives_up(
    client: SecClient, tmp_path, monkeypatch
) -> None:
    responses.add(responses.GET, FILE_URL, body=b"never arrives whole")

    def always_drops(self, *args, **kwargs):
        yield b"partial"
        raise requests.exceptions.ChunkedEncodingError("connection dropped")

    monkeypatch.setattr(requests.Response, "iter_content", always_drops)
    dest = tmp_path / "master.idx"

    with pytest.raises(SecRetriesExhaustedError):
        client.download(FILE_URL, dest)
    assert not dest.exists(), "a truncated file must never be left on disk"


# -- rate limiting ------------------------------------------------------------


def test_token_bucket_spaces_requests(clock: FakeClock) -> None:
    bucket = TokenBucket(rate=5, clock=clock.time, sleep=clock.sleep)

    for _ in range(11):
        bucket.acquire()

    # The first request goes at once; the next ten wait 0.2 s each: 2 s in total.
    assert clock.now == pytest.approx(2.0)


@responses.activate
def test_client_never_exceeds_its_rate(clock: FakeClock) -> None:
    responses.add(responses.GET, URL, json={})
    client = SecClient(USER_AGENT, rate_per_second=5, clock=clock.time, sleep=clock.sleep)

    for _ in range(26):
        client.get_json(URL)

    # 26 requests at 5 per second need at least 5 seconds.
    assert clock.now >= 5.0
