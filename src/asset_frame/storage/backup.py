"""Backup of the operating data: a consistent SQLite copy plus the immutable raw files."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import date
from pathlib import Path

KEEP_DATABASE_COPIES = 4


def backup(database: Path, raw_root: Path, destination: Path, today: date) -> tuple[Path, int]:
    """Copy the database (SQLite backup API) and any raw file the destination lacks.

    Raw files are write-once, so an existing destination file is never overwritten.
    Only the newest KEEP_DATABASE_COPIES database copies are kept.
    """
    database_dir = destination / "db"
    database_dir.mkdir(parents=True, exist_ok=True)
    target = database_dir / f"asset_frame-{today:%Y%m%d}.sqlite3"
    source = sqlite3.connect(database)
    copy = sqlite3.connect(target)
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()

    copied = 0
    for path in raw_root.rglob("*"):
        if not path.is_file():
            continue
        out = destination / "raw" / path.relative_to(raw_root)
        if out.exists():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        copied += 1

    for old in sorted(database_dir.glob("asset_frame-*.sqlite3"))[:-KEEP_DATABASE_COPIES]:
        old.unlink()
    return target, copied
