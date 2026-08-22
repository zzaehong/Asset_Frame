from decimal import Decimal

from asset_frame.storage.budget import BYTES_PER_GIB, evaluate_storage_budget


def test_storage_budget_is_a_warning_not_a_hard_limit() -> None:
    status = evaluate_storage_budget(
        raw_store_bytes=8 * BYTES_PER_GIB,
        database_bytes=3 * BYTES_PER_GIB,
        warning_gb=Decimal("10"),
    )
    assert status.warning is True
    assert status.total_bytes == 11 * BYTES_PER_GIB


def test_storage_budget_allows_unknown_database_size() -> None:
    status = evaluate_storage_budget(
        raw_store_bytes=2 * BYTES_PER_GIB,
        database_bytes=None,
        warning_gb=Decimal("10"),
    )
    assert status.warning is False
