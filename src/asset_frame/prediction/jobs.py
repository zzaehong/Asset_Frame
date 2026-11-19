from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from asset_frame.prediction.models import (
    HORIZON_MONTHS,
    MODELS,
    momentum_ranking,
    persistence_probability,
    random_ranking,
)
from asset_frame.prediction.scoring import (
    brier,
    horizon_months,
    mean_with_mde,
    rank_ic,
    realized_returns,
    top_bottom_spread,
)
from asset_frame.regime.replay import stock_bond_correlation
from asset_frame.storage.ledger import LedgerStore

CALC_VERSION = "prediction_v1"
PREDICTION = "prediction"
SCORE = "score"
Returns = Mapping[str, Mapping[date, float]]


def record_predictions(
    ledger: LedgerStore, returns: Returns, anchors: Sequence[str], month_ends: list[date]
) -> int:
    """Append the model predictions for the latest month end; returns how many were new."""
    as_of = max(month_ends)
    correlation = stock_bond_correlation(returns, month_ends, as_of)
    rankings = {
        "momentum_12_1": (
            momentum_ranking(returns, anchors, month_ends),
            persistence_probability(correlation),
        ),
        "equal_rank": (random_ranking(anchors, as_of), 0.5),
    }
    appended = 0
    for model in MODELS:
        ranking, probability = rankings[model]
        if not ranking or probability is None:
            continue
        appended += _append_prediction(ledger, model, as_of, ranking, probability, note="")
    return appended


def record_human_prediction(
    ledger: LedgerStore,
    anchors: Sequence[str],
    month_ends: list[date],
    ranking: Sequence[str],
    probability_positive: float,
    note: str,
) -> bool:
    """The user's prediction for the latest month end (one per month). Raises ValueError if
    the ranking is not a list of distinct anchors or the probability is outside [0, 1]."""
    if len(set(ranking)) != len(ranking) or not set(ranking) <= set(anchors):
        raise ValueError(f"ranking must be distinct tickers from: {', '.join(anchors)}")
    if len(ranking) < 6:
        raise ValueError("ranking needs at least 6 tickers (top 3 and bottom 3)")
    if not 0 <= probability_positive <= 1:
        raise ValueError("probability must be between 0 and 1")
    return _append_prediction(
        ledger, "human", max(month_ends), list(ranking), probability_positive, note
    )


def _append_prediction(
    ledger: LedgerStore, model: str, as_of: date, ranking: list[str], p_positive: float, note: str
) -> bool:
    payload = {
        "calc_version": CALC_VERSION,
        "model": model,
        "as_of": as_of.isoformat(),
        "horizon_months": HORIZON_MONTHS,
        "ranking": ranking,
        "p_correlation_positive": p_positive,
        "note": note,
    }
    return ledger.append(PREDICTION, payload, key=f"{PREDICTION}:{model}:{as_of}") is not None


def score_due(ledger: LedgerStore, returns: Returns, month_ends: list[date]) -> int:
    """Score every unscored prediction whose horizon is complete; returns how many were scored."""
    entries = ledger.entries()
    scored = {json.loads(e.payload)["prediction_seq"] for e in entries if e.entry_type == SCORE}
    count = 0
    for entry in entries:
        if entry.entry_type != PREDICTION or entry.seq in scored:
            continue
        prediction = json.loads(entry.payload)
        as_of = date.fromisoformat(prediction["as_of"])
        months = horizon_months(month_ends, as_of)
        if months is None:
            continue
        realized = realized_returns(returns, prediction["ranking"], months)
        correlation = stock_bond_correlation(returns, month_ends, months[-1])
        payload = {
            "calc_version": CALC_VERSION,
            "prediction_seq": entry.seq,
            "model": prediction["model"],
            "as_of": prediction["as_of"],
            "horizon_end": months[-1].isoformat(),
            "n_assets": len(realized),
            "ic": rank_ic(prediction["ranking"], realized),
            "spread": top_bottom_spread(prediction["ranking"], realized),
            "brier": None
            if correlation is None
            else brier(prediction["p_correlation_positive"], correlation > 0),
            "realized_correlation": correlation,
        }
        ledger.append(SCORE, payload, key=f"{SCORE}:{entry.seq}")
        count += 1
    return count


@dataclass(frozen=True, slots=True)
class Board:
    model: str
    scored: int
    mean_ic: float | None
    ic_mde: float | None
    mean_spread: float | None
    mean_brier: float | None


def scoreboard(ledger: LedgerStore) -> tuple[Board, ...]:
    by_model: dict[str, list[dict]] = defaultdict(list)
    for entry in ledger.entries():
        if entry.entry_type == SCORE:
            payload = json.loads(entry.payload)
            by_model[payload["model"]].append(payload)
    boards = []
    for model, items in sorted(by_model.items()):
        ics = [i["ic"] for i in items if i["ic"] is not None]
        spreads = [i["spread"] for i in items if i["spread"] is not None]
        briers = [i["brier"] for i in items if i["brier"] is not None]
        mean_ic, ic_mde = mean_with_mde(ics) if ics else (None, None)
        boards.append(
            Board(
                model,
                len(items),
                mean_ic,
                ic_mde,
                sum(spreads) / len(spreads) if spreads else None,
                sum(briers) / len(briers) if briers else None,
            )
        )
    return tuple(boards)
