from __future__ import annotations

from asset_frame.regime.replay import RULES, RegimeRow, RuleScore, replay, score
from asset_frame.regime.rules import SERIES_FOR_RULES
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
