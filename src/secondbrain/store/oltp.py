"""Encrypted SQLite OLTP store.

AES-256 via SQLCipher, key custody in the macOS Keychain. This module is the
single chokepoint for OLTP writes (captures, app capability, audit log).
Vector and graph stores live in their own modules.

Cipher swap note: when SQLite3 Multiple Ciphers ships a py3.13 wheel, the
import line below changes; the public API does not.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import keyring

try:
    from sqlcipher3 import dbapi2 as sqlcipher  # type: ignore[import-not-found]
except ImportError as e:  # pragma: no cover - dependency check
    raise RuntimeError("sqlcipher3-wheels not installed; see spikes/requirements.txt") from e


CAPTURES_SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    id                    TEXT PRIMARY KEY,
    source                TEXT NOT NULL,
    captured_at           REAL NOT NULL,
    app_name              TEXT,
    app_bundle_id         TEXT,
    window_title          TEXT,
    url                   TEXT,
    file_path             TEXT,
    ax_text               TEXT,
    ocr_text              TEXT,
    text_hash             BLOB,
    pixel_hash            BLOB,
    pixel_path            TEXT,
    sensitive             INTEGER NOT NULL DEFAULT 0,
    redacted              INTEGER NOT NULL DEFAULT 0,
    monitor_index         INTEGER,
    capability_cache_hit  INTEGER NOT NULL DEFAULT 0,
    gate                  TEXT NOT NULL DEFAULT 'persist',
    meta_json             TEXT
);
CREATE INDEX IF NOT EXISTS captures_captured_at_idx
    ON captures(captured_at);
CREATE INDEX IF NOT EXISTS captures_app_idx
    ON captures(app_bundle_id, app_name);
"""


# Schema migrations. Append-only. Each entry is (version, sql).
# `user_version` PRAGMA tracks where the DB currently sits; missing migrations
# are applied in order on open. Never edit a shipped migration — add a new one.
SCHEMA_MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        # v1 is the baseline captures table, created by CAPTURES_SCHEMA;
        # registered here so user_version reflects the shipped schema.
        CAPTURES_SCHEMA,
    ),
]
CURRENT_SCHEMA_VERSION = SCHEMA_MIGRATIONS[-1][0]


class SchemaTooNew(RuntimeError):
    """DB was written by a newer SecondBrain than this binary knows about."""


class IntegrityCheckFailed(RuntimeError):
    """`PRAGMA integrity_check` returned something other than 'ok'.

    Recovery: restore from the most recent `secondbrain backup`.
    """


def _apply_migrations(conn) -> None:
    """Bring conn forward to CURRENT_SCHEMA_VERSION. Idempotent."""
    cur = conn.execute("PRAGMA user_version").fetchone()
    current = int(cur[0]) if cur else 0
    if current > CURRENT_SCHEMA_VERSION:
        raise SchemaTooNew(
            f"DB user_version={current} > code's CURRENT_SCHEMA_VERSION="
            f"{CURRENT_SCHEMA_VERSION}. Upgrade SecondBrain or restore an "
            f"older backup."
        )
    for version, sql in SCHEMA_MIGRATIONS:
        if version > current:
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()


def _integrity_check(conn) -> None:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    if not row or row[0] != "ok":
        raise IntegrityCheckFailed(
            f"PRAGMA integrity_check returned {row!r}. Restore from a recent `secondbrain backup`."
        )


# `Connection` exists so test code can swap SQLCipher for sqlite3 in
# unit tests where encryption is irrelevant. Production always uses SQLCipher.
class Connection(Protocol):
    def execute(self, sql: str, params: tuple = ...) -> sqlite3.Cursor: ...
    def executescript(self, sql: str) -> sqlite3.Cursor: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class StoreConfig:
    db_path: Path
    keyring_service: str = "secondbrain.device_root_key"
    keyring_user: str = "default"


def _ensure_device_root_key(cfg: StoreConfig) -> str:
    """Read or generate the device root key in the OS keychain."""
    existing = keyring.get_password(cfg.keyring_service, cfg.keyring_user)
    if existing:
        return existing
    fresh = os.urandom(32).hex()
    keyring.set_password(cfg.keyring_service, cfg.keyring_user, fresh)
    return fresh


def open_encrypted(cfg: StoreConfig, *, check_integrity: bool = True) -> Connection:
    """Open (or create) the encrypted OLTP DB. Idempotent.

    Runs `PRAGMA integrity_check` once per open, then applies any pending
    schema migrations. A corrupt DB raises `IntegrityCheckFailed`; a DB
    written by a newer release raises `SchemaTooNew`. Neither condition is
    silently recovered from — operators must respond explicitly.
    """
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    key_hex = _ensure_device_root_key(cfg)

    conn = sqlcipher.connect(str(cfg.db_path), check_same_thread=False)
    conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    if check_integrity:
        _integrity_check(conn)
    _apply_migrations(conn)
    return conn  # type: ignore[return-value]


def open_unencrypted(path: Path | str, *, check_integrity: bool = True) -> sqlite3.Connection:
    """For tests that don't need encryption. Production code must use `open_encrypted`.

    `check_same_thread=False`: the aiohttp gateway runs in a different
    thread from the CLI's main loop; SQLite serializes writes internally so
    a single shared connection is safe as long as we don't hand cursors
    across threads.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    if check_integrity:
        _integrity_check(conn)
    _apply_migrations(conn)
    return conn
