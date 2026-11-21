"""Trailing dividend yield from raw per-share cash dividends and the raw close.

Price basis: raw close on ``as_of``. Dividends: Tiingo ``divCash`` on the ex-date in that day's
share units, so a later split divides them. USD, no tax, no reinvestment.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

CALC_VERSION = "dividend_yield_v1"
WINDOW_MONTHS = 12


@dataclass(frozen=True)
class DividendYield:
    calc_version: str
    as_of: date
    window_start: date
    close: Decimal
    annual_per_share: Decimal
    dividend_yield: Decimal
    payments: int


def _one_year_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # Feb 29
        return day.replace(year=day.year - 1, day=28)


def trailing_dividend_yield(
    dividends: Iterable[tuple[date, Decimal]],
    splits: Iterable[tuple[date, Decimal]],
    close: Decimal,
    as_of: date,
    first_price_date: date,
) -> DividendYield | None:
    """Sum of dividends with ex-date in (as_of − 12 months, as_of], split-adjusted, over ``close``.

    Returns None when the price history is shorter than the window or the close is not positive.
    Dividends repeated on the same ex-date (re-ingested snapshots) count once.
    """
    start = _one_year_before(as_of)
    if close <= 0 or first_price_date > start:
        return None
    split_list = [(day, factor) for day, factor in splits if start < day <= as_of]
    unique = {day: amount for day, amount in dividends if start < day <= as_of}
    total = Decimal(0)
    for day, amount in unique.items():
        divisor = Decimal(1)
        for split_day, factor in split_list:
            if split_day > day:
                divisor *= factor
        total += amount / divisor
    return DividendYield(CALC_VERSION, as_of, start, close, total, total / close, len(unique))
