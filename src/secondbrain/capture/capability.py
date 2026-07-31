"""Per-app capability cache.

Records, per (app_name, app_bundle_id), whether the AX (accessibility) tree
yielded usable text on past captures. Avoids re-probing every session.

The cache lives in the encrypted SQLite DB. Schema is intentionally tiny: one
row per (bundle_id, app_name) with success/total counters, last-seen timestamps,
and a derived `usable` boolean cached via a hysteresis policy.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass


@dataclass
class CapabilityRecord:
    bundle_id: str
    app_name: str
    ax_success: int
    ax_total: int
    last_success_ts: float | None
    last_attempt_ts: float
    usable: bool


SCHEMA = """
CREATE TABLE IF NOT EXISTS app_capability (
    bundle_id        TEXT NOT NULL,
    app_name         TEXT NOT NULL,
    ax_success       INTEGER NOT NULL DEFAULT 0,
    ax_total         INTEGER NOT NULL DEFAULT 0,
    last_success_ts  REAL,
    last_attempt_ts  REAL NOT NULL,
    usable           INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (bundle_id, app_name)
);
"""


# Hysteresis, so a single bad sample never flips `usable`:
#   OFF: 5 consecutive misses since the last hit
#   ON:  at least 3 hits AND >=70% success rate over the window
class CapabilityCache:
    """Thin SQLite-backed registry of which apps expose AX text reliably."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.executescript(SCHEMA)
        self._misses_since_last_hit: dict[tuple[str, str], int] = {}

    def record(
        self,
        bundle_id: str,
        app_name: str,
        ax_text_present: bool,
    ) -> CapabilityRecord:
        """Record one observation; return the current cached state."""
        now = time.time()
        key = (bundle_id, app_name)
        cur = self.conn.execute(
            "SELECT ax_success, ax_total, last_success_ts, usable "
            "FROM app_capability WHERE bundle_id=? AND app_name=?",
            (bundle_id, app_name),
        ).fetchone()
        if cur is None:
            success = 1 if ax_text_present else 0
            total = 1
            last_success = now if ax_text_present else None
            usable = bool(ax_text_present)  # bootstrap on first sample
        else:
            success = int(cur[0]) + (1 if ax_text_present else 0)
            total = int(cur[1]) + 1
            last_success = now if ax_text_present else cur[2]
            usable = bool(cur[3])

        if ax_text_present:
            self._misses_since_last_hit[key] = 0
            if success >= 3 and (success / total) >= 0.7:
                usable = True
        else:
            self._misses_since_last_hit[key] = self._misses_since_last_hit.get(key, 0) + 1
            # Flip OFF after 5 consecutive misses.
            if self._misses_since_last_hit[key] >= 5:
                usable = False

        self.conn.execute(
            "INSERT INTO app_capability "
            "(bundle_id, app_name, ax_success, ax_total, "
            " last_success_ts, last_attempt_ts, usable) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(bundle_id, app_name) DO UPDATE SET "
            "ax_success=excluded.ax_success, "
            "ax_total=excluded.ax_total, "
            "last_success_ts=excluded.last_success_ts, "
            "last_attempt_ts=excluded.last_attempt_ts, "
            "usable=excluded.usable",
            (
                bundle_id,
                app_name,
                success,
                total,
                last_success,
                now,
                int(usable),
            ),
        )
        self.conn.commit()
        return CapabilityRecord(
            bundle_id=bundle_id,
            app_name=app_name,
            ax_success=success,
            ax_total=total,
            last_success_ts=last_success,
            last_attempt_ts=now,
            usable=usable,
        )

    def is_usable(self, bundle_id: str, app_name: str) -> bool | None:
        """Return cached usability; None if we have never seen this app."""
        cur = self.conn.execute(
            "SELECT usable FROM app_capability WHERE bundle_id=? AND app_name=?",
            (bundle_id, app_name),
        ).fetchone()
        if cur is None:
            return None
        return bool(cur[0])
