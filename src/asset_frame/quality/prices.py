from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from asset_frame.domain.models import PriceObservation, QualityStatus


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    message: str
    trading_date: date | None


@dataclass(frozen=True, slots=True)
class PriceValidationResult:
    status: QualityStatus
    issues: tuple[QualityIssue, ...]


def validate_prices(prices: tuple[PriceObservation, ...]) -> PriceValidationResult:
    issues: list[QualityIssue] = []
    seen_dates: set[date] = set()
    previous_date: date | None = None

    for price in prices:
        if price.open is None or price.high is None or price.low is None:
            issues.append(
                QualityIssue(
                    "incomplete_ohlc",
                    "open, high, low, and close are all required",
                    price.trading_date,
                )
            )
        if price.trading_date in seen_dates:
            issues.append(
                QualityIssue("duplicate_date", "duplicate trading date", price.trading_date)
            )
        seen_dates.add(price.trading_date)
        if previous_date is not None and price.trading_date <= previous_date:
            issues.append(
                QualityIssue(
                    "date_order", "prices must be strictly date ordered", price.trading_date
                )
            )
        previous_date = price.trading_date

        positive_values = (price.open, price.high, price.low, price.close, price.adjusted_close)
        if any(value is not None and value <= 0 for value in positive_values):
            issues.append(
                QualityIssue("non_positive_price", "prices must be positive", price.trading_date)
            )
        if price.volume is not None and price.volume < 0:
            issues.append(
                QualityIssue("negative_volume", "volume must not be negative", price.trading_date)
            )
        if price.high is not None and price.low is not None and price.high < price.low:
            issues.append(QualityIssue("high_below_low", "high is below low", price.trading_date))
        if price.high is not None:
            if price.open is not None and price.open > price.high:
                issues.append(
                    QualityIssue("open_above_high", "open is above high", price.trading_date)
                )
            if price.close > price.high:
                issues.append(
                    QualityIssue("close_above_high", "close is above high", price.trading_date)
                )
        if price.low is not None:
            if price.open is not None and price.open < price.low:
                issues.append(
                    QualityIssue("open_below_low", "open is below low", price.trading_date)
                )
            if price.close < price.low:
                issues.append(
                    QualityIssue("close_below_low", "close is below low", price.trading_date)
                )

    status = QualityStatus.QUARANTINED if issues else QualityStatus.ACCEPTED
    return PriceValidationResult(status=status, issues=tuple(issues))


def compare_close_prices(
    primary: PriceObservation,
    validation: PriceObservation,
    *,
    relative_tolerance: Decimal,
) -> PriceValidationResult:
    if primary.asset_id != validation.asset_id or primary.trading_date != validation.trading_date:
        return PriceValidationResult(
            status=QualityStatus.QUARANTINED,
            issues=(QualityIssue("comparison_key_mismatch", "asset or date differs", None),),
        )
    if relative_tolerance < 0:
        raise ValueError("relative tolerance must not be negative")

    difference = abs(primary.close - validation.close) / primary.close
    if difference > relative_tolerance:
        return PriceValidationResult(
            status=QualityStatus.QUARANTINED,
            issues=(
                QualityIssue(
                    "close_source_conflict",
                    f"relative close difference {difference} exceeds {relative_tolerance}",
                    primary.trading_date,
                ),
            ),
        )
    return PriceValidationResult(status=QualityStatus.ACCEPTED, issues=())
