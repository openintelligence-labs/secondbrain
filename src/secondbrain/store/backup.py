"""Coordinated backup/restore for the full SecondBrain data root.

The "data root" is the directory containing the encrypted OLTP DB plus its
sibling stores:

    <db_path>             — encrypted SQLite (captures, audit log)
    <db_path>.parent/lance/   — LanceDB chunk vectors
    <db_path>.parent/tantivy/ — BM25 index
    <db_path>.parent/kg/      — Kùzu knowledge graph

A backup is a single .tar.gz containing those four trees plus a `manifest.json`
recording schema version, file SHA-256s, and a timestamp. Restore refuses to
overwrite unless the caller passes `force=True`.

TODO: refuse restore while a daemon holds the target path; the lock file the
detection would read is not written yet.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from secondbrain.store.oltp import CURRENT_SCHEMA_VERSION

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = "secondbrain.backup.v1"


@dataclass(frozen=True)
class BackupManifest:
    schema: str
    created_at: str
    secondbrain_version: str
    schema_version: int
    files: dict[str, str]  # relpath -> sha256 hex

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema": self.schema,
                "created_at": self.created_at,
                "secondbrain_version": self.secondbrain_version,
                "schema_version": self.schema_version,
                "files": self.files,
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, blob: str) -> BackupManifest:
        data = json.loads(blob)
        if data.get("schema") != MANIFEST_SCHEMA:
            raise ValueError(f"unknown manifest schema: {data.get('schema')!r}")
        return cls(
            schema=data["schema"],
            created_at=data["created_at"],
            secondbrain_version=data["secondbrain_version"],
            schema_version=int(data["schema_version"]),
            files=dict(data["files"]),
        )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _walk(root: Path) -> list[Path]:
    """Sorted file list under root (skip directories, follow no symlinks)."""
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out.append(p)
    return out


def _candidate_subdirs(db_path: Path) -> list[Path]:
    """Sibling stores that should be included in a backup if present."""
    base = db_path.parent
    return [base / "lance", base / "tantivy", base / "kg", base / "lance_visual"]


def make_backup(
    db_path: Path,
    out_path: Path,
    *,
    secondbrain_version: str,
) -> BackupManifest:
    """Snapshot the data root into a single .tar.gz at out_path.

    Returns the manifest. Raises FileNotFoundError if db_path doesn't exist.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"OLTP DB not found at {db_path}")

    db_path = db_path.resolve()
    base = db_path.parent
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    targets: list[Path] = [db_path]
    for d in _candidate_subdirs(db_path):
        if d.exists() and d.is_dir():
            targets.extend(_walk(d))

    files_hash: dict[str, str] = {}
    for p in targets:
        rel = p.relative_to(base).as_posix()
        files_hash[rel] = _sha256_file(p)

    manifest = BackupManifest(
        schema=MANIFEST_SCHEMA,
        created_at=datetime.now(UTC).isoformat(),
        secondbrain_version=secondbrain_version,
        schema_version=CURRENT_SCHEMA_VERSION,
        files=files_hash,
    )

    with tarfile.open(out_path, "w:gz") as tar:
        manifest_bytes = manifest.to_json().encode("utf-8")
        info = tarfile.TarInfo(name=MANIFEST_NAME)
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))
        for p in targets:
            rel = p.relative_to(base).as_posix()
            tar.add(p, arcname=rel)
    return manifest


def read_manifest(archive: Path) -> BackupManifest:
    with tarfile.open(archive, "r:gz") as tar:
        try:
            f = tar.extractfile(MANIFEST_NAME)
        except KeyError as e:
            raise ValueError(f"{archive} is not a SecondBrain backup (no manifest)") from e
        if f is None:
            raise ValueError(f"{archive} manifest is unreadable")
        blob = f.read().decode("utf-8")
    return BackupManifest.from_json(blob)


def restore_backup(
    archive: Path,
    db_path: Path,
    *,
    force: bool = False,
) -> BackupManifest:
    """Extract archive into db_path's parent. Refuses if files exist unless
    force=True. Validates every file's SHA-256 against the manifest before
    declaring success — a corrupt archive is detected, not silently restored.
    """
    archive = archive.resolve()
    db_path = db_path.resolve()
    base = db_path.parent
    base.mkdir(parents=True, exist_ok=True)

    manifest = read_manifest(archive)

    if manifest.schema_version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"archive schema_version={manifest.schema_version} > code's "
            f"CURRENT_SCHEMA_VERSION={CURRENT_SCHEMA_VERSION}. Upgrade SecondBrain."
        )

    existing = [base / rel for rel in manifest.files if (base / rel).exists()]
    if existing and not force:
        raise FileExistsError(
            f"refusing to overwrite {len(existing)} existing path(s) under {base}. "
            "Re-run with force=True (or pass --force on the CLI)."
        )

    # Extract into a temp staging dir, validate, then atomically swap.
    staging = base / ".restore-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        with tarfile.open(archive, "r:gz") as tar:
            # Filter out the manifest itself and anything that isn't in the
            # declared file list — defense against path traversal.
            declared = set(manifest.files.keys()) | {MANIFEST_NAME}
            for member in tar.getmembers():
                if member.name not in declared:
                    raise ValueError(f"archive contains undeclared entry: {member.name!r}")
                if member.name == MANIFEST_NAME:
                    continue
                # Reject absolute paths and ".." traversal.
                if member.name.startswith("/") or ".." in Path(member.name).parts:
                    raise ValueError(f"unsafe path in archive: {member.name!r}")
                # Python 3.12+ requires explicit filter; `data` strips owner
                # bits and re-rejects unsafe paths.
                tar.extract(member, path=staging, filter="data")

        # Validate hashes.
        for rel, want in manifest.files.items():
            got = _sha256_file(staging / rel)
            if got != want:
                raise ValueError(f"hash mismatch on {rel}: got {got[:12]}…, want {want[:12]}…")

        # Atomic-ish swap: move staged files in. If any target exists with
        # force=True, replace it.
        for rel in manifest.files:
            src = staging / rel
            dst = base / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            shutil.move(str(src), str(dst))
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    return manifest
