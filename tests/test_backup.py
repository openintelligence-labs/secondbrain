"""Backup + restore tests — round-trip with hash validation, refuse to clobber,
and reject tampered archives."""
from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

import pytest

from secondbrain.store import backup as backup_mod
from secondbrain.store.oltp import open_unencrypted


def _seed(tmp_path: Path) -> Path:
    db = tmp_path / "sb" / "secondbrain.db"
    conn = open_unencrypted(db)
    conn.execute(
        "INSERT INTO captures (id, source, captured_at, app_name) VALUES (?,?,?,?)",
        ("c1", "test", 1.0, "TestApp"),
    )
    conn.commit()
    conn.close()
    # Fake the sibling stores so backup picks them up.
    (db.parent / "lance").mkdir()
    (db.parent / "lance" / "table.bin").write_bytes(b"lance-data")
    (db.parent / "tantivy").mkdir()
    (db.parent / "tantivy" / "seg.idx").write_bytes(b"tantivy-data")
    (db.parent / "kg").mkdir()
    (db.parent / "kg" / "meta.kuzu").write_bytes(b"kuzu-data")
    return db


def test_backup_then_restore_roundtrip(tmp_path: Path) -> None:
    db = _seed(tmp_path)
    archive = tmp_path / "snapshot.tar.gz"
    manifest = backup_mod.make_backup(db, archive, secondbrain_version="test")
    assert archive.exists()
    assert manifest.schema_version >= 1
    assert "secondbrain.db" in manifest.files

    # Wipe the data root, then restore.
    shutil.rmtree(db.parent)
    backup_mod.restore_backup(archive, db)

    conn = open_unencrypted(db)
    rows = conn.execute("SELECT id, app_name FROM captures").fetchall()
    conn.close()
    assert rows == [("c1", "TestApp")]
    assert (db.parent / "lance" / "table.bin").read_bytes() == b"lance-data"
    assert (db.parent / "tantivy" / "seg.idx").read_bytes() == b"tantivy-data"
    assert (db.parent / "kg" / "meta.kuzu").read_bytes() == b"kuzu-data"


def test_restore_refuses_to_clobber_without_force(tmp_path: Path) -> None:
    db = _seed(tmp_path)
    archive = tmp_path / "snapshot.tar.gz"
    backup_mod.make_backup(db, archive, secondbrain_version="test")

    with pytest.raises(FileExistsError):
        backup_mod.restore_backup(archive, db)


def test_restore_with_force_overwrites(tmp_path: Path) -> None:
    db = _seed(tmp_path)
    archive = tmp_path / "snapshot.tar.gz"
    backup_mod.make_backup(db, archive, secondbrain_version="test")

    # Mutate the live DB so we can prove restore actually rolled it back.
    conn = open_unencrypted(db)
    conn.execute("INSERT INTO captures (id, source, captured_at) VALUES ('c2','t',2)")
    conn.commit()
    conn.close()

    backup_mod.restore_backup(archive, db, force=True)
    conn = open_unencrypted(db)
    ids = sorted(r[0] for r in conn.execute("SELECT id FROM captures").fetchall())
    conn.close()
    assert ids == ["c1"]


def test_tampered_archive_fails_hash_check(tmp_path: Path) -> None:
    db = _seed(tmp_path)
    archive = tmp_path / "snapshot.tar.gz"
    backup_mod.make_backup(db, archive, secondbrain_version="test")

    # Rebuild the archive with a file mutated, manifest unchanged.
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(archive, "r:gz") as src, tarfile.open(tampered, "w:gz") as dst:
        for member in src.getmembers():
            f = src.extractfile(member)
            data = f.read() if f else b""
            if member.name.endswith("table.bin"):
                data = b"EVIL" + data[4:]
            member.size = len(data)
            import io as _io
            dst.addfile(member, _io.BytesIO(data))

    shutil.rmtree(db.parent)
    with pytest.raises(ValueError, match="hash mismatch"):
        backup_mod.restore_backup(tampered, db)


def test_archive_with_path_traversal_rejected(tmp_path: Path) -> None:
    """Defense in depth: even if a malicious manifest declares ../etc/passwd,
    the extractor must refuse before writing anything."""
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        import io as _io
        manifest = (
            '{"schema":"secondbrain.backup.v1","created_at":"x",'
            '"secondbrain_version":"x","schema_version":1,'
            '"files":{"../escape.txt":"00"}}'
        )
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest.encode())
        tar.addfile(info, _io.BytesIO(manifest.encode()))
        escape = b"pwned"
        info2 = tarfile.TarInfo(name="../escape.txt")
        info2.size = len(escape)
        tar.addfile(info2, _io.BytesIO(escape))

    with pytest.raises(ValueError, match="unsafe path"):
        backup_mod.restore_backup(archive, tmp_path / "sb" / "secondbrain.db")
