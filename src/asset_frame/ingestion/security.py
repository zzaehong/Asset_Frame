from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_QUERY_KEYS = {
    "api_key",
    "apikey",
    "api-key",
    "key",
    "token",
    "access_token",
    "crtfc_key",
    "secret",
}


def mask_url_secrets(url: str) -> str:
    parts = urlsplit(url)
    masked_query = urlencode(
        [
            (key, "***" if key.casefold() in _SENSITIVE_QUERY_KEYS else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, masked_query, parts.fragment))
