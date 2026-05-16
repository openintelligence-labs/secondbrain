"""Audit log.

Every retrieval emits a row: who asked, what query, which capture_ids were
cited. This is the primary GDPR Art. 30 evidence and the input to
`secondbrain compliance audit` exports.

Schema lives next to the OLTP DB (same encryption regime). Exports sign the
full log so external auditors can verify nothing was altered.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from dataclasses import dataclass


SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    actor       TEXT,             -- 'cli', 'mcp:claude', etc
    action      TEXT NOT NULL,    -- 'search', 'forget', 'export'
    query       TEXT,
    cited_json  TEXT,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS audit_log_ts_idx ON audit_log(ts);
"""


@dataclass
class AuditLog:
    conn: sqlite3.Connection

    def __post_init__(self) -> None:
        self.conn.executescript(SCHEMA)

    def record(
        self,
        action: str,
        *,
        actor: str = "cli",
        query: str | None = None,
        cited: list[str] | None = None,
        detail: dict | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO audit_log (ts, actor, action, query, cited_json, detail_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                time.time(),
                actor,
                action,
                query,
                json.dumps(cited or []),
                json.dumps(detail or {}),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def export_signed(self, *, signing_key32: bytes) -> dict:
        rows = list(
            self.conn.execute(
                "SELECT id, ts, actor, action, query, cited_json, detail_json "
                "FROM audit_log ORDER BY id ASC"
            )
        )
        entries = []
        for r in rows:
            entries.append(
                {
                    "id": r[0],
                    "ts": r[1],
                    "actor": r[2],
                    "action": r[3],
                    "query": r[4],
                    "cited": json.loads(r[5]) if r[5] else [],
                    "detail": json.loads(r[6]) if r[6] else {},
                }
            )
        canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
        sig = hmac.new(signing_key32, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "schema": "secondbrain.audit.v1",
            "signature_hmac_sha256": sig,
            "entries": entries,
            "exported_at": time.time(),
        }
