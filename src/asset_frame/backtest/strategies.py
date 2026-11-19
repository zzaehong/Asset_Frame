"""Strategy definitions (config/strategies.toml) and their target weights for one month."""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from asset_frame.universe import UniverseAsset

KINDS = ("fixed", "equal_weight")
MEMBER_SETS = ("level1_anchors",)


class StrategyConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Strategy:
    id: str
    role: str
    kind: str
    weights: dict[str, float] = field(default_factory=dict)
    members: tuple[str, ...] = ()


def load_strategies(path: Path, universe: Sequence[UniverseAsset]) -> tuple[Strategy, ...]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    tickers = {asset.ticker for asset in universe}
    level1_anchors = tuple(a.ticker for a in universe if a.level == 1 and a.role == "anchor")
    strategies = []
    for entry in document["strategies"]:
        strategy_id, kind = entry["id"], entry["kind"]
        if kind not in KINDS:
            raise StrategyConfigError(f"{strategy_id}: unknown kind {kind}")
        if kind == "fixed":
            weights = {ticker: float(weight) for ticker, weight in entry["weights"].items()}
            unknown = set(weights) - tickers
            if unknown:
                raise StrategyConfigError(
                    f"{strategy_id}: tickers not in universe: {sorted(unknown)}"
                )
            if abs(sum(weights.values()) - 1) > 1e-9:
                raise StrategyConfigError(f"{strategy_id}: weights must sum to 1")
            strategies.append(Strategy(strategy_id, entry["role"], kind, weights=weights))
        else:
            if entry["members"] not in MEMBER_SETS:
                raise StrategyConfigError(f"{strategy_id}: unknown member set {entry['members']}")
            strategies.append(Strategy(strategy_id, entry["role"], kind, members=level1_anchors))
    ids = [s.id for s in strategies]
    if len(ids) != len(set(ids)):
        raise StrategyConfigError("duplicate strategy id")
    return tuple(strategies)


def target_weights(strategy: Strategy, eligible: Sequence[str]) -> tuple[dict[str, float], float]:
    """Target weights over the eligible assets (sum 1) and coverage, the share of the
    strategy's intended weight that those assets carry. Empty weights when nothing is eligible."""
    available = set(eligible)
    if strategy.kind == "fixed":
        usable = {t: w for t, w in strategy.weights.items() if t in available}
        coverage = sum(usable.values())
        if coverage <= 0:
            return {}, 0.0
        return {t: w / coverage for t, w in usable.items()}, coverage
    usable_members = [t for t in strategy.members if t in available]
    if not usable_members:
        return {}, 0.0
    return (
        {t: 1 / len(usable_members) for t in usable_members},
        len(usable_members) / len(strategy.members),
    )
