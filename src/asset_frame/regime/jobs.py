from __future__ import annotations

from dataclasses import asdict

from asset_frame.regime.long import LONG_START, long_month_ends
from asset_frame.regime.replay import RULES, RegimeRow, RuleScore, ip_quadrants, replay, score
from asset_frame.regime.rules import CALC_VERSION, SERIES_FOR_RULES
from asset_frame.storage.ledger import LedgerStore
from asset_frame.storage.research import ResearchStore


def first_release_series(store: ResearchStore) -> dict:
    series = {}
    for series_id in SERIES_FOR_RULES:
        releases = store.macro_first_releases(series_id)
        if not releases:
            raise SystemExit(
                f"no {series_id} data: run `asset-frame ingest-fred --series {series_id}`"
            )
        series[series_id] = [
            (m, released, float(v)) for m, released, v in releases if v is not None
        ]
    return series


def run_regime(store: ResearchStore) -> tuple[tuple[RegimeRow, ...], tuple[RuleScore, ...]]:
    series = first_release_series(store)
    usrec = {point.observation_date: point.value == 1 for point in store.macro_points("USREC")}
    if not usrec:
        raise SystemExit("no USREC data: run `asset-frame ingest-fred --series USREC`")
    returns = {
        ticker: {month: float(value) for month, value in by_month.items()}
        for ticker, by_month in store.latest_returns().items()
    }
    if "SPY" not in returns:
        raise SystemExit("no monthly returns: run `asset-frame build-returns`")
    rows = replay(series, usrec, returns, sorted(returns["SPY"]))
    return rows, tuple(score(rows, rule) for rule in RULES)


def run_regime_long(
    store: ResearchStore,
) -> tuple[tuple[RegimeRow, ...], list[str | None], dict[str, dict]]:
    """Replay from LONG_START with proxy-extended returns; also the INDPRO/CPI quadrant.

    Returns (rows, quadrant_ip aligned to rows, float returns per ticker incl. proxy months).
    Rows before the funds' history have no stock-bond correlation; rules lacking inputs are None.
    """
    from asset_frame.proxy_jobs import merged_returns

    series = first_release_series(store)
    usrec = {point.observation_date: point.value == 1 for point in store.macro_points("USREC")}
    returns = {
        ticker: {month: float(value) for month, value in by_month.items()}
        for ticker, by_month in merged_returns(store).items()
    }
    if "SPY" not in returns:
        raise SystemExit("no monthly returns: run `asset-frame build-returns`")
    month_ends = long_month_ends({m for by_month in returns.values() for m in by_month})
    rows = replay(series, usrec, returns, month_ends, start=LONG_START)
    return rows, ip_quadrants(series, [row.month_end for row in rows]), returns


REGIME_ENTRY = "regime_observation"


def record_regime(
    ledger: LedgerStore, rows: tuple[RegimeRow, ...], *, replay_all: bool
) -> tuple[int, int]:
    """Append regime rows to the ledger: the latest month as `live`, or every month as `replay`.

    Returns (appended, already present). Re-running never duplicates a month.
    """
    kind = "replay" if replay_all else "live"
    appended = skipped = 0
    for row in rows if replay_all else rows[-1:]:
        payload = {
            "calc_version": CALC_VERSION,
            "kind": kind,
            **(asdict(row) | {"month_end": row.month_end.isoformat()}),
        }
        key = f"{REGIME_ENTRY}:{row.month_end}:{CALC_VERSION}:{kind}"
        if ledger.append(REGIME_ENTRY, payload, key=key) is None:
            skipped += 1
        else:
            appended += 1
    return appended, skipped
