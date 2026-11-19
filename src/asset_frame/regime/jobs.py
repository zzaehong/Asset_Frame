from __future__ import annotations

from dataclasses import asdict

from asset_frame.regime.replay import RULES, RegimeRow, RuleScore, replay, score
from asset_frame.regime.rules import CALC_VERSION, SERIES_FOR_RULES
from asset_frame.storage.ledger import LedgerStore
from asset_frame.storage.research import ResearchStore


def run_regime(store: ResearchStore) -> tuple[tuple[RegimeRow, ...], tuple[RuleScore, ...]]:
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
