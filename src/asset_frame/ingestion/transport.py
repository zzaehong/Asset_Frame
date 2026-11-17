from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import Message
from time import monotonic, sleep
from typing import Protocol

from asset_frame.domain.models import FetchRequest, FetchResponse


class TransportError(RuntimeError):
    pass


class HttpTransport(Protocol):
    def fetch(self, request: FetchRequest) -> FetchResponse: ...


class UrllibHttpTransport:
    def fetch(self, request: FetchRequest) -> FetchResponse:
        http_request = urllib.request.Request(request.url, headers=request.headers)
        try:
            with urllib.request.urlopen(http_request, timeout=request.timeout_seconds) as response:
                return FetchResponse(
                    status_code=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                    fetched_at=datetime.now(UTC),
                )
        except urllib.error.HTTPError as error:
            return FetchResponse(
                status_code=error.code,
                body=error.read(),
                headers=_headers(error.headers),
                fetched_at=datetime.now(UTC),
            )
        except (urllib.error.URLError, TimeoutError) as error:
            message = f"official source request failed: {type(error).__name__}"
            raise TransportError(message) from error


class RateLimitedRetryTransport:
    """Space requests and retry transient HTTP responses from a wrapped transport."""

    def __init__(
        self,
        transport: HttpTransport,
        *,
        minimum_interval_seconds: float,
        max_attempts: int = 4,
        backoff_seconds: float = 5.0,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if minimum_interval_seconds < 0:
            raise ValueError("minimum request interval must not be negative")
        if max_attempts < 1:
            raise ValueError("max attempts must be positive")
        if backoff_seconds < 0:
            raise ValueError("retry backoff must not be negative")
        self._transport = transport
        self._minimum_interval_seconds = minimum_interval_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleeper = sleeper
        self._clock = clock
        self._last_request_at: float | None = None

    def fetch(self, request: FetchRequest) -> FetchResponse:
        for attempt in range(1, self._max_attempts + 1):
            self._wait_for_request_slot()
            response = self._transport.fetch(request)
            if response.status_code not in {429, 500, 502, 503, 504}:
                return response
            if attempt == self._max_attempts:
                return response
            retry_after = _retry_after_seconds(response.headers)
            exponential_backoff = self._backoff_seconds * (2 ** (attempt - 1))
            self._sleeper(max(retry_after, exponential_backoff))
        raise AssertionError("retry loop must return a response")

    def _wait_for_request_slot(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            remaining = self._minimum_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                self._sleeper(remaining)
                now = self._clock()
        self._last_request_at = now


def _headers(headers: Message | None) -> dict[str, str]:
    return dict(headers.items()) if headers is not None else {}


def _retry_after_seconds(headers: dict[str, str]) -> float:
    value = next((value for name, value in headers.items() if name.lower() == "retry-after"), None)
    if value is None:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        return 0.0
