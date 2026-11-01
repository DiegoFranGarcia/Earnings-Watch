"""A polite HTTP client for sec.gov.

The SEC allows at most 10 requests per second and requires automated clients
to declare who they are. This client:

- sends a declared User-Agent and Accept-Encoding on every request,
- spaces requests with a token bucket (5 per second by default),
- retries 429, 5xx and network errors with exponential backoff and jitter,
- stops at once on 403, which means the SEC is throttling or blocking us,
- streams downloads to disk while computing their SHA-256.
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
EPSILON = 1e-9  # absorbs floating-point rounding in the token bucket
CHUNK_SIZE = 1024 * 1024  # 1 MiB
STREAM_ERRORS = (
    requests.exceptions.ChunkedEncodingError,  # connection dropped mid-file
    requests.exceptions.ContentDecodingError,  # gzip stream cut short
    requests.exceptions.ConnectionError,
)


class SecError(RuntimeError):
    """Base class for sec.gov errors."""


class SecForbiddenError(SecError):
    """403: the SEC is throttling or blocking us. Never retry automatically."""


class SecNotFoundError(SecError):
    """404: the file does not exist, or not yet. The caller decides which."""


class SecRetriesExhaustedError(SecError):
    """A retryable failure kept happening on every attempt."""


class TokenBucket:
    """Lets through at most `rate` requests per second, shared by all threads."""

    def __init__(
        self,
        rate: float,
        capacity: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a request is allowed."""
        with self._lock:
            while True:
                now = self._clock()
                refill = (now - self._updated) * self.rate
                self._tokens = min(self.capacity, self._tokens + refill)
                self._updated = now
                if self._tokens >= 1 - EPSILON:
                    self._tokens = max(0.0, self._tokens - 1)
                    return
                self._sleep((1 - self._tokens) / self.rate)


@dataclass(frozen=True)
class RemoteFile:
    """What a HEAD request says about a file, without downloading it."""

    size_bytes: int | None  # None when the size is unknown or is a compressed transfer size
    last_modified: str | None


@dataclass(frozen=True)
class DownloadResult:
    """What we know about a file after downloading it."""

    url: str
    path: Path
    size_bytes: int
    sha256: str
    last_modified: str | None


class SecClient:
    """All traffic to sec.gov goes through one of these."""

    def __init__(
        self,
        user_agent: str,
        rate_per_second: float = 5.0,
        max_attempts: int = 5,
        backoff_base: float = 1.0,
        backoff_cap: float = 60.0,
        timeout: tuple[float, float] = (10.0, 60.0),
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if "@" not in user_agent:
            raise ValueError(
                "The SEC requires a contact email in the User-Agent, "
                "for example 'EarningsWatch you@example.com'."
            )
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.timeout = timeout
        self._sleep = sleep
        self._bucket = TokenBucket(rate_per_second, clock=clock, sleep=sleep)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})

    # -- public API ---------------------------------------------------------

    def get_json(self, url: str) -> Any:
        """GET a JSON document, such as an EDGAR directory's index.json."""
        with self._request("GET", url) as response:
            return response.json()

    def exists(self, url: str) -> bool:
        """HEAD a URL: True if it exists, False on 404."""
        try:
            self._request("HEAD", url).close()
        except SecNotFoundError:
            return False
        return True

    def metadata(self, url: str) -> RemoteFile | None:
        """HEAD a URL: its size and Last-Modified date, or None on 404."""
        try:
            response = self._request("HEAD", url)
        except SecNotFoundError:
            return None
        with response:
            headers = response.headers
            length = headers.get("Content-Length")
            # A compressed transfer reports the compressed size, not the file's own size.
            compressed = headers.get("Content-Encoding", "identity") != "identity"
            size = int(length) if length is not None and not compressed else None
            return RemoteFile(size_bytes=size, last_modified=headers.get("Last-Modified"))

    def download(self, url: str, dest: Path) -> DownloadResult:
        """Stream a file to `dest`, hashing as it goes. Never holds it in memory.

        A connection that drops mid-file is retried from the start; a partial
        file is never left behind.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, self.max_attempts + 1):
            response = self._request("GET", url, stream=True)
            digest = hashlib.sha256()
            size = 0
            try:
                with response, dest.open("wb") as out:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        out.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            except STREAM_ERRORS as exc:
                dest.unlink(missing_ok=True)
                if attempt == self.max_attempts:
                    raise SecRetriesExhaustedError(
                        f"Download of {url} failed {attempt} times"
                    ) from exc
                self._wait_before_retry(attempt, url, exc, retry_after=None)
                continue
            return DownloadResult(
                url=url,
                path=dest,
                size_bytes=size,
                sha256=digest.hexdigest(),
                last_modified=response.headers.get("Last-Modified"),
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> SecClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- internals ----------------------------------------------------------

    def _request(self, method: str, url: str, stream: bool = False) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._bucket.acquire()
            retry_after: str | None = None
            try:
                response = self.session.request(method, url, stream=stream, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
            else:
                status = response.status_code
                if status == 403:
                    response.close()
                    raise SecForbiddenError(
                        f"403 Forbidden from {url}. The SEC is throttling or blocking "
                        "this client: stop, then check the User-Agent and request rate."
                    )
                if status == 404:
                    response.close()
                    raise SecNotFoundError(f"404 Not Found: {url}")
                if status not in RETRYABLE_STATUS:
                    response.raise_for_status()  # other 4xx: a bug on our side
                    return response
                retry_after = response.headers.get("Retry-After")
                last_error = requests.HTTPError(f"{status} from {url}", response=response)
                response.close()
            if attempt < self.max_attempts:
                self._wait_before_retry(attempt, url, last_error, retry_after)
        raise SecRetriesExhaustedError(
            f"{method} {url} failed {self.max_attempts} times"
        ) from last_error

    def _wait_before_retry(
        self, attempt: int, url: str, error: Exception | None, retry_after: str | None
    ) -> None:
        if retry_after is not None and retry_after.isdigit():
            delay = min(float(retry_after), self.backoff_cap)
        else:
            # "Full jitter": a random wait up to an exponentially growing ceiling,
            # so many clients that failed together don't all retry together.
            ceiling = min(self.backoff_cap, self.backoff_base * 2**attempt)
            delay = random.uniform(0, ceiling)  # noqa: S311 - jitter, not cryptography
        log.warning(
            "Attempt %d/%d for %s failed (%s); retrying in %.1fs",
            attempt,
            self.max_attempts,
            url,
            error,
            delay,
        )
        self._sleep(delay)
