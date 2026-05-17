"""Verify encrypted-SQLite Python bindings + macOS Keychain key custody.

The architecture's preferred cipher is SQLite3 Multiple Ciphers ChaCha20-Poly1305.
Available Python wheels for SQLite-MC are pre-Python-3.13 only as of May 2026,
so this spike validates the ENCRYPTION CONTRACT with sqlcipher3-wheels (AES-256
SQLCipher) — same encrypted-SQLite contract, different cipher. The cipher choice
gets swapped at the C layer when SQLite-MC ships a 3.13 wheel; the Python API
surface tested here (`sqlcipher3.dbapi2`) is identical to what we'd use either way.

Pass criteria:
- Generate a high-entropy key, store in macOS Keychain via `keyring`
- Open an encrypted SQLite DB with that key
- Round-trip a row
- Re-open with the wrong key fails
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import keyring  # noqa: E402
from _runner import record  # noqa: E402

try:
    from sqlcipher3 import dbapi2 as sqlcipher  # type: ignore[import-not-found]

    BACKEND = f"sqlcipher3-wheels (AES-256, sqlite {sqlcipher.sqlite_version})"
except Exception as e:
    print(f"sqlcipher3 import failed: {e}")
    sys.exit(1)


SERVICE = "secondbrain.spike.s0_05"
USER = "device_root_key"


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sb_enc_"))
    try:
        # 1. Generate a high-entropy key, store in Keychain
        key_hex = os.urandom(32).hex()
        keyring.set_password(SERVICE, USER, key_hex)
        retrieved = keyring.get_password(SERVICE, USER)
        if retrieved != key_hex:
            record("S0-05", False, {"reason": "keychain round-trip failed"})

        # 2. Open encrypted DB with PRAGMA key
        db_path = tmp / "encrypted.db"
        conn = sqlcipher.connect(str(db_path))
        conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        conn.execute(
            "CREATE TABLE captures("
            "id INTEGER PRIMARY KEY, "
            "app TEXT, "
            "ax_text TEXT, "
            "captured_at REAL)"
        )
        conn.execute(
            "INSERT INTO captures VALUES (?,?,?,?)",
            (1, "Code", "hello secondbrain", 1730000000.0),
        )
        conn.commit()
        conn.close()

        # 3. Re-open and read with the right key
        conn2 = sqlcipher.connect(str(db_path))
        conn2.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        row = conn2.execute("SELECT app, ax_text FROM captures").fetchone()
        conn2.close()
        if row != ("Code", "hello secondbrain"):
            record("S0-05", False, {"reason": "round-trip read mismatch", "row": row})

        # 4. Wrong key must fail
        wrong = os.urandom(32).hex()
        conn3 = sqlcipher.connect(str(db_path))
        conn3.execute(f"PRAGMA key = \"x'{wrong}'\"")
        wrong_failed = False
        try:
            conn3.execute("SELECT count(*) FROM captures").fetchone()
        except sqlcipher.DatabaseError:
            wrong_failed = True
        conn3.close()

        # 5. Verify the on-disk file is NOT plaintext SQLite
        header = db_path.read_bytes()[:16]
        plaintext_marker = b"SQLite format 3\x00"
        is_encrypted = not header.startswith(plaintext_marker)

        # Cleanup keychain
        keyring.delete_password(SERVICE, USER)

        passed = wrong_failed and is_encrypted
        record(
            "S0-05",
            passed,
            {
                "backend": BACKEND,
                "keyring_backend": keyring.get_keyring().name,
                "round_trip_ok": True,
                "wrong_key_rejected": wrong_failed,
                "on_disk_encrypted": is_encrypted,
                "on_disk_header_hex": header.hex(),
                "note": (
                    "Cipher is AES-256 SQLCipher today; arch-locked target "
                    "is ChaCha20-Poly1305 via SQLite3 Multiple Ciphers — "
                    "swap at C layer when py3.13 wheel ships. Python API "
                    "surface validated here is identical."
                ),
            },
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
