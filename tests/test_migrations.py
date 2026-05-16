"""Schema migration + integrity check tests for store/oltp.py."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from secondbrain.store.oltp import (
    CURRENT_SCHEMA_VERSION,
    IntegrityCheckFailed,
    SchemaTooNew,
    open_unencrypted,
)


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def test_fresh_db_lands_at_current_version(tmp_path: Path) -> None:
    conn = open_unencrypted(tmp_path / "fresh.db")
    assert _user_version(conn) == CURRENT_SCHEMA_VERSION
    conn.close()


def test_reopen_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "twice.db"
    c1 = open_unencrypted(db)
    c1.execute("INSERT INTO captures (id, source, captured_at) VALUES ('a','t',0)")
    c1.commit()
    c1.close()

    c2 = open_unencrypted(db)
    rows = c2.execute("SELECT id FROM captures").fetchall()
    assert rows == [("a",)]
    assert _user_version(c2) == CURRENT_SCHEMA_VERSION
    c2.close()


def test_pre_versioned_db_migrates_forward(tmp_path: Path) -> None:
    """A DB created before we tracked user_version (PRAGMA user_version=0)
    must still get the captures table created and end up at CURRENT."""
    db = tmp_path / "legacy.db"
    raw = sqlite3.connect(db)
    raw.execute("PRAGMA user_version=0")
    raw.commit()
    raw.close()

    conn = open_unencrypted(db)
    assert _user_version(conn) == CURRENT_SCHEMA_VERSION
    conn.execute("INSERT INTO captures (id, source, captured_at) VALUES ('m','t',0)")
    conn.commit()
    conn.close()


def test_future_db_version_refuses_to_open(tmp_path: Path) -> None:
    db = tmp_path / "future.db"
    raw = sqlite3.connect(db)
    raw.execute(f"PRAGMA user_version={CURRENT_SCHEMA_VERSION + 99}")
    raw.commit()
    raw.close()

    with pytest.raises(SchemaTooNew):
        open_unencrypted(db)


def test_corrupted_db_raises_integrity_error(tmp_path: Path) -> None:
    db = tmp_path / "corrupt.db"
    # Build a valid DB first so the file is a real SQLite header...
    conn = open_unencrypted(db)
    conn.execute("INSERT INTO captures (id, source, captured_at) VALUES ('x','t',0)")
    conn.commit()
    conn.close()

    # ...then scribble over the middle of the page where data lives.
    with open(db, "r+b") as f:
        f.seek(0x2000)
        f.write(b"\x00" * 4096)

    with pytest.raises(IntegrityCheckFailed):
        open_unencrypted(db)


def test_integrity_check_can_be_disabled_for_recovery(tmp_path: Path) -> None:
    """Disaster-recovery escape hatch: when an operator is trying to dump
    data from a corrupt DB, they can re-open with check_integrity=False."""
    db = tmp_path / "skip.db"
    conn = open_unencrypted(db)
    conn.close()
    with open(db, "r+b") as f:
        f.seek(0x2000)
        f.write(b"\x00" * 4096)
    # No exception — caller has explicitly accepted the risk.
    conn2 = open_unencrypted(db, check_integrity=False)
    conn2.close()
