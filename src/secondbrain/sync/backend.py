"""Pluggable sync backends."""
from __future__ import annotations

import json
import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from secondbrain.store.crypt.age_files import decrypt_from_path, encrypt_to_path


class SyncBackend(Protocol):
    name: str

    def push(self, kind: str, payload: dict[str, Any]) -> None: ...
    def pull(self) -> list[tuple[str, dict[str, Any]]]: ...
    def status(self) -> dict[str, Any]: ...


@dataclass
class InMemoryBackend:
    """Used by tests; round-trips items in process."""

    name: str = "memory"
    _outbox: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _inbox: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def push(self, kind: str, payload: dict[str, Any]) -> None:
        self._outbox.append((kind, payload))

    def pull(self) -> list[tuple[str, dict[str, Any]]]:
        out, self._inbox = self._inbox, []
        return out

    def deliver_to_peer(self, peer: "InMemoryBackend") -> None:
        peer._inbox.extend(self._outbox)
        self._outbox.clear()

    def status(self) -> dict[str, Any]:
        return {"backend": self.name, "outbox": len(self._outbox), "inbox": len(self._inbox)}


@dataclass
class SyncthingBackend:
    """v0 sync — encrypted JSON blobs in a Syncthing-watched folder.

    Operator setup:
      1. Install Syncthing on both devices.
      2. Point each at the same folder (`folder` arg below).
      3. Pair the X25519 keys with `secondbrain pair` (writes a `peers.json`
         in the folder). Each blob is encrypted under the pre-shared 32-byte
         key derived from the pairing handshake.

    Wire format: every push writes
        <folder>/<device_id>-<utc_ns>-<rand>.sbsync
    which is an age-encrypted JSON object `{"kind": str, "payload": ...}`.
    Pull scans for blobs whose device_id != ours, attempts decryption, and
    returns the decrypted (kind, payload) tuples while marking the blob seen.

    The "seen" set lives in `<folder>/.seen/<device_id>.txt` (one filename per
    line, append-only). Syncthing's own .stignore should be configured to
    leave `.seen/` local — see the daemon README for the full ignore file.
    """

    folder: str
    psk: bytes  # 32 bytes — derived from X25519 pairing
    device_id: str = ""
    name: str = "syncthing"
    _seen_cache: set[str] = field(default_factory=set)

    BLOB_SUFFIX = ".sbsync"

    def __post_init__(self) -> None:
        if len(self.psk) != 32:
            raise ValueError("SyncthingBackend.psk must be 32 bytes")
        if not self.device_id:
            # Stable per-host fallback — host name is fine because the wire
            # format includes a per-blob nonce. Pairing UI will overwrite this.
            self.device_id = socket.gethostname().replace("/", "_")[:32] or "dev"
        Path(self.folder).mkdir(parents=True, exist_ok=True)
        (Path(self.folder) / ".seen").mkdir(exist_ok=True)
        self._load_seen()

    @property
    def _seen_path(self) -> Path:
        return Path(self.folder) / ".seen" / f"{self.device_id}.txt"

    def _load_seen(self) -> None:
        if self._seen_path.exists():
            self._seen_cache = set(
                line.strip()
                for line in self._seen_path.read_text().splitlines()
                if line.strip()
            )

    def _mark_seen(self, name: str) -> None:
        self._seen_cache.add(name)
        with self._seen_path.open("a") as f:
            f.write(name + "\n")

    def push(self, kind: str, payload: dict[str, Any]) -> None:
        record = {"kind": kind, "payload": payload}
        blob = json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ts = time.time_ns()
        rand = secrets.token_hex(4)
        name = f"{self.device_id}-{ts}-{rand}{self.BLOB_SUFFIX}"
        encrypt_to_path(blob, Path(self.folder) / name, key32=self.psk)

    def pull(self) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        for p in sorted(Path(self.folder).glob(f"*{self.BLOB_SUFFIX}")):
            name = p.name
            if name in self._seen_cache:
                continue
            # Skip blobs we wrote ourselves — Syncthing reflects everything.
            if name.startswith(self.device_id + "-"):
                self._mark_seen(name)
                continue
            try:
                raw = decrypt_from_path(p, key32=self.psk)
                record = json.loads(raw.decode("utf-8"))
                out.append((record["kind"], record["payload"]))
                self._mark_seen(name)
            except Exception:
                # Bad/foreign blob — leave it alone (another peer may handle it).
                # We do NOT mark seen so a key rotation can revisit it.
                continue
        return out

    def status(self) -> dict[str, Any]:
        n_blobs = len(list(Path(self.folder).glob(f"*{self.BLOB_SUFFIX}")))
        return {
            "backend": self.name,
            "folder": self.folder,
            "device_id": self.device_id,
            "blobs_in_folder": n_blobs,
            "seen": len(self._seen_cache),
        }


@dataclass
class IrohBackend:
    """Locked target — Iroh + Automerge, lands once iroh-blobs ≥1.0 stabilizes."""

    name: str = "iroh"

    def push(self, kind: str, payload: dict[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError("Iroh + Automerge backend not yet wired")

    def pull(self) -> list[tuple[str, dict[str, Any]]]:  # pragma: no cover
        raise NotImplementedError("Iroh + Automerge backend not yet wired")

    def status(self) -> dict[str, Any]:  # pragma: no cover
        return {"backend": self.name}


__all__ = [
    "SyncBackend",
    "InMemoryBackend",
    "SyncthingBackend",
    "IrohBackend",
]
