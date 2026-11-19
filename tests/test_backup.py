import sqlite3
from datetime import date, timedelta
from pathlib import Path

from asset_frame.storage.backup import KEEP_DATABASE_COPIES, backup


def test_backup_copies_database_and_new_raw_files_only(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("create table t (x integer)")
    connection.execute("insert into t values (7)")
    connection.commit()
    connection.close()
    raw = tmp_path / "raw"
    (raw / "a").mkdir(parents=True)
    (raw / "a" / "one.json").write_text("v1")
    destination = tmp_path / "backup"

    target, copied = backup(database, raw, destination, date(2026, 11, 19))

    assert copied == 1
    assert sqlite3.connect(target).execute("select x from t").fetchone() == (7,)
    (raw / "a" / "two.json").write_text("v2")
    (destination / "raw" / "a" / "one.json").write_text("kept")  # never overwritten
    _, copied = backup(database, raw, destination, date(2026, 11, 20))
    assert copied == 1
    assert (destination / "raw" / "a" / "one.json").read_text() == "kept"


def test_backup_keeps_only_the_newest_database_copies(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite3"
    sqlite3.connect(database).close()
    raw = tmp_path / "raw"
    raw.mkdir()
    start = date(2026, 11, 1)
    for offset in range(KEEP_DATABASE_COPIES + 2):
        backup(database, raw, tmp_path / "b", start + timedelta(days=offset))

    names = sorted(p.name for p in (tmp_path / "b" / "db").glob("*.sqlite3"))
    assert len(names) == KEEP_DATABASE_COPIES
    assert names[-1] == "asset_frame-20261106.sqlite3"
