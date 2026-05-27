"""Captures repository — write/read against the OLTP DB."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from secondbrain.models import Capture

COLUMNS = (
    "id, source, captured_at, app_name, app_bundle_id, window_title, url, "
    "file_path, ax_text, ocr_text, text_hash, pixel_hash, pixel_path, "
    "sensitive, redacted, monitor_index, capability_cache_hit, gate, meta_json"
)


def insert(conn: sqlite3.Connection, capture: Capture) -> None:
    conn.execute(
        f"INSERT INTO captures ({COLUMNS}) VALUES ({', '.join('?' * len(COLUMNS.split(', ')))})",
        (
            capture.id,
            capture.source,
            capture.captured_at.timestamp(),
            capture.app_name,
            capture.app_bundle_id,
            capture.window_title,
            capture.url,
            str(capture.file_path) if capture.file_path else None,
            capture.ax_text,
            capture.ocr_text,
            capture.text_hash,
            capture.pixel_hash,
            str(capture.pixel_path) if capture.pixel_path else None,
            int(capture.sensitive),
            int(capture.redacted),
            capture.monitor_index,
            int(capture.capability_cache_hit),
            capture.gate,
            json.dumps(capture.meta) if capture.meta else None,
        ),
    )
    conn.commit()


def count(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM captures")
    return int(cur.fetchone()[0])


def recent(conn: sqlite3.Connection, limit: int = 50) -> Iterable[dict]:
    cur = conn.execute(
        f"SELECT {COLUMNS} FROM captures ORDER BY captured_at DESC LIMIT ?",
        (limit,),
    )
    cols = [c.strip() for c in COLUMNS.split(",")]
    for row in cur.fetchall():
        yield dict(zip(cols, row, strict=True))
