from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

BYTES_PER_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class StorageBudgetStatus:
    raw_store_bytes: int
    database_bytes: int | None
    warning_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.raw_store_bytes + (self.database_bytes or 0)

    @property
    def warning(self) -> bool:
        return self.total_bytes >= self.warning_bytes


def measure_raw_store(path: Path) -> int:
    if not path.exists():
        return 0
    if not path.is_dir():
        raise ValueError("raw store path must be a directory")
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def evaluate_storage_budget(
    *, raw_store_bytes: int, database_bytes: int | None, warning_gb: Decimal
) -> StorageBudgetStatus:
    if raw_store_bytes < 0 or (database_bytes is not None and database_bytes < 0):
        raise ValueError("storage byte counts cannot be negative")
    if warning_gb <= 0:
        raise ValueError("warning_gb must be positive")
    return StorageBudgetStatus(
        raw_store_bytes=raw_store_bytes,
        database_bytes=database_bytes,
        warning_bytes=int(warning_gb * BYTES_PER_GIB),
    )
