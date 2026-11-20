from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from asset_frame.domain.models import FetchRequest, MacroObservation, RawSnapshot

FRED_SOURCE_ID = "fred"
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
# Series replayed as first published (output_type=4: initial release only; realtime_start is the
# release date). DTB3, the yield-curve spreads and the dollar index are market series that FRED does
# not revise, FEDFUNDS is a monthly average of the policy rate, and USREC is NBER dating used only
# to score: all of these are read at the current vintage.
FIRST_RELEASE_SERIES = ("INDPRO", "CFNAIMA3", "UNRATE", "CPIAUCSL")
RATE_SERIES = ("DTB3", "T10Y3M", "T10Y2Y", "FEDFUNDS", "DTWEXBGS", "DTWEXM")
SUPPORTED_SERIES = (*RATE_SERIES, *FIRST_RELEASE_SERIES, "USREC")
_EARLIEST_REALTIME = "1776-07-04"  # FRED's documented lower bound for realtime_start
_LATEST_REALTIME = "9999-12-31"
_MISSING_VALUE = "."


class FredPayloadError(ValueError):
    pass


def build_observations_request(series_id: str, api_key: str) -> FetchRequest:
    if series_id not in SUPPORTED_SERIES:
        raise ValueError(f"FRED series is not approved for collection: {series_id}")
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json"}
    if series_id in FIRST_RELEASE_SERIES:
        params |= {
            "realtime_start": _EARLIEST_REALTIME,
            "realtime_end": _LATEST_REALTIME,
            "output_type": "4",
        }
    query = urlencode(params)
    return FetchRequest(url=f"{FRED_OBSERVATIONS_URL}?{query}")


def parse_observations(
    body: bytes, *, series_id: str, snapshot: RawSnapshot
) -> tuple[MacroObservation, ...]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise FredPayloadError("FRED response is not valid JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
        raise FredPayloadError("FRED response must contain an observations list")
    rows = payload["observations"]
    if int(payload.get("count", len(rows))) != len(rows) + int(payload.get("offset", 0)):
        raise FredPayloadError("FRED response is partial; count does not match observations")
    observations = []
    for row in rows:
        try:
            observations.append(
                MacroObservation(
                    source_id=FRED_SOURCE_ID,
                    raw_snapshot_id=snapshot.id,
                    series_id=series_id,
                    observation_date=date.fromisoformat(row["date"]),
                    value=_value(row["value"]),
                    realtime_start=date.fromisoformat(row["realtime_start"]),
                    realtime_end=date.fromisoformat(row["realtime_end"]),
                    fetched_at=snapshot.fetched_at,
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FredPayloadError(f"invalid FRED observation: {error}") from error
    return tuple(observations)


def _value(raw: str) -> Decimal | None:
    if raw == _MISSING_VALUE:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise FredPayloadError(f"FRED value is not numeric: {raw!r}") from error
    if not value.is_finite():
        raise FredPayloadError("FRED value must be finite")
    return value
