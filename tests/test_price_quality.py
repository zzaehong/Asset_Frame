from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from asset_frame.domain.models import PriceObservation, QualityStatus
from asset_frame.quality.prices import compare_close_prices, validate_prices


def make_price(**changes: object) -> PriceObservation:
    price = PriceObservation(
        asset_id=uuid4(),
        source_id="primary",
        raw_snapshot_id=uuid4(),
        trading_date=date(2026, 8, 20),
        currency="USD",
        open=Decimal("99"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("100"),
        adjusted_close=Decimal("100"),
        volume=Decimal("1000"),
        fetched_at=datetime(2026, 8, 21, tzinfo=UTC),
        price_basis="raw",
    )
    return replace(price, **changes)


def test_invalid_ohlc_is_quarantined() -> None:
    result = validate_prices((make_price(high=Decimal("97")),))

    assert result.status is QualityStatus.QUARANTINED
    assert {issue.code for issue in result.issues} >= {"high_below_low", "close_above_high"}


def test_conflicting_sources_are_not_averaged() -> None:
    asset_id = uuid4()
    primary = make_price(asset_id=asset_id, close=Decimal("100"))
    validation = make_price(asset_id=asset_id, source_id="validation", close=Decimal("103"))

    result = compare_close_prices(primary, validation, relative_tolerance=Decimal("0.01"))

    assert result.status is QualityStatus.QUARANTINED
    assert result.issues[0].code == "close_source_conflict"
