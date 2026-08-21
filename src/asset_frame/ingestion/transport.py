from __future__ import annotations

import urllib.error
import urllib.request
from datetime import UTC, datetime
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
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            message = f"official source request failed: {type(error).__name__}"
            raise TransportError(message) from error
