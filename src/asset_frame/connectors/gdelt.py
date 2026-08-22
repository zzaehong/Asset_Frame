from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

from asset_frame.domain.models import FetchRequest, NewsArticleMention, RawSnapshot

GDELT_SOURCE_ID = "gdelt-doc"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_USER_AGENT = "Asset-Frame/0.1 (GDELT DOC metadata collector)"


class GdeltPayloadError(ValueError):
    pass


def build_news_request(
    *, query: str, start_at: datetime, end_at: datetime, max_records: int = 75
) -> FetchRequest:
    if not query.strip():
        raise ValueError("GDELT query is required")
    if start_at.tzinfo is None or end_at.tzinfo is None or start_at > end_at:
        raise ValueError("GDELT start/end timestamps must be ordered and timezone-aware")
    if end_at - start_at > timedelta(days=90):
        raise ValueError("GDELT news window must not exceed 90 days")
    if not 1 <= max_records <= 250:
        raise ValueError("GDELT max_records must be between 1 and 250")
    query_string = urlencode(
        {
            "query": query.strip(),
            "mode": "artlist",
            "format": "json",
            "sort": "datedesc",
            "maxrecords": max_records,
            "startdatetime": start_at.astimezone(UTC).strftime("%Y%m%d%H%M%S"),
            "enddatetime": end_at.astimezone(UTC).strftime("%Y%m%d%H%M%S"),
        }
    )
    return FetchRequest(
        url=f"{GDELT_DOC_URL}?{query_string}",
        headers={"Accept": "application/json", "User-Agent": GDELT_USER_AGENT},
        timeout_seconds=60,
    )


def parse_news(
    body: bytes,
    *,
    asset_id: UUID,
    snapshot: RawSnapshot,
    matched_query: str,
) -> tuple[NewsArticleMention, ...]:
    try:
        payload = json.loads(body)
        articles = payload["articles"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise GdeltPayloadError("invalid GDELT article list payload") from error
    if not isinstance(articles, list):
        raise GdeltPayloadError("GDELT articles must be a list")
    mentions = []
    seen: set[str] = set()
    for row in articles:
        if not isinstance(row, dict):
            raise GdeltPayloadError("GDELT article row must be an object")
        url = _required(row, "url")
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise GdeltPayloadError("GDELT article URL is invalid")
        if url in seen:
            continue
        seen.add(url)
        mentions.append(
            NewsArticleMention(
                id=uuid5(NAMESPACE_URL, f"{GDELT_SOURCE_ID}:{url}"),
                asset_id=asset_id,
                source_id=GDELT_SOURCE_ID,
                raw_snapshot_id=snapshot.id,
                article_url=url,
                title=_required(row, "title"),
                source_domain=_optional(row, "domain") or parsed_url.netloc,
                language=_optional(row, "language"),
                source_country=_optional(row, "sourcecountry"),
                published_at=_timestamp(_required(row, "seendate")),
                fetched_at=snapshot.fetched_at,
                matched_query=matched_query,
            )
        )
    return tuple(mentions)


def _required(row: dict[str, object], name: str) -> str:
    value = _optional(row, name)
    if value is None:
        raise GdeltPayloadError(f"GDELT article field is missing: {name}")
    return value


def _optional(row: dict[str, object], name: str) -> str | None:
    value = row.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _timestamp(value: str) -> datetime:
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise GdeltPayloadError("GDELT article timestamp is invalid")
