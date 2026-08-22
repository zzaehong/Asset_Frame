from email.message import Message
from io import BytesIO
from urllib.error import HTTPError

import pytest

from asset_frame.domain.models import FetchRequest, FetchResponse
from asset_frame.ingestion.transport import RateLimitedRetryTransport, UrllibHttpTransport


class SequenceTransport:
    def __init__(self, responses: list[FetchResponse]) -> None:
        self.responses = responses
        self.calls = 0

    def fetch(self, request: FetchRequest) -> FetchResponse:
        response = self.responses[self.calls]
        self.calls += 1
        return response


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _response(status_code: int, *, retry_after: str | None = None) -> FetchResponse:
    from datetime import UTC, datetime

    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return FetchResponse(status_code, b"body", headers, datetime(2026, 8, 22, tzinfo=UTC))


def test_urllib_transport_preserves_http_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = Message()
    headers["Content-Type"] = "text/plain"

    def raise_http_error(*args: object, **kwargs: object) -> None:
        raise HTTPError(
            "https://example.test",
            429,
            "Too Many Requests",
            headers,
            BytesIO(b"limit requests"),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)

    response = UrllibHttpTransport().fetch(FetchRequest("https://example.test"))

    assert response.status_code == 429
    assert response.body == b"limit requests"
    assert response.headers["Content-Type"] == "text/plain"


def test_rate_limited_transport_retries_with_retry_after_and_spacing() -> None:
    fake_time = FakeTime()
    inner = SequenceTransport([_response(429, retry_after="7"), _response(200), _response(200)])
    transport = RateLimitedRetryTransport(
        inner,
        minimum_interval_seconds=5,
        max_attempts=3,
        backoff_seconds=5,
        sleeper=fake_time.sleep,
        clock=fake_time.clock,
    )

    response = transport.fetch(FetchRequest("https://example.test"))
    second = transport.fetch(FetchRequest("https://example.test"))

    assert response.status_code == 200
    assert second.status_code == 200
    assert inner.calls == 3
    assert fake_time.sleeps == [7.0, 5.0]


def test_rate_limited_transport_returns_last_transient_response() -> None:
    fake_time = FakeTime()
    inner = SequenceTransport([_response(503), _response(503)])
    transport = RateLimitedRetryTransport(
        inner,
        minimum_interval_seconds=5,
        max_attempts=2,
        sleeper=fake_time.sleep,
        clock=fake_time.clock,
    )

    response = transport.fetch(FetchRequest("https://example.test"))

    assert response.status_code == 503
    assert inner.calls == 2
    assert fake_time.sleeps == [5.0]
