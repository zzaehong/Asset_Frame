from pathlib import Path

import pytest

from asset_frame.storage.migrations import migrate_database


def test_migration_requires_sql_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no database migrations"):
        migrate_database("postgresql://unused", tmp_path)
