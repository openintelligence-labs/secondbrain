"""Device pairing.

Strategy: each device generates an X25519 pubkey, displays its short
fingerprint as a QR + a 24-word age recovery phrase. Peer scans, confirms,
and they exchange short-term sync keys. Recovery phrase is the user's
"escape hatch" if a device is lost.

This module ships the cryptographic primitives (fingerprints, pseudo-recovery
word list) so the pairing UX can wire them up against a real Tauri front-end.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

# TODO: replace this BIP-39-style stand-in with the canonical 2048-word list
# before the Tauri pairing UX ships.
_WORDS = [
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "romeo",
    "sierra",
    "tango",
    "uniform",
    "victor",
    "whiskey",
    "xray",
    "yankee",
    "zulu",
]


@dataclass
class DeviceIdentity:
    private_key: X25519PrivateKey
    public_key_bytes: bytes

    @classmethod
    def fresh(cls) -> DeviceIdentity:
        sk = X25519PrivateKey.generate()
        pk = sk.public_key().public_bytes_raw()
        return cls(private_key=sk, public_key_bytes=pk)

    def fingerprint_hex(self) -> str:
        digest = hashlib.sha256(self.public_key_bytes).digest()
        return digest[:8].hex()

    def fingerprint_words(self) -> list[str]:
        digest = hashlib.sha256(self.public_key_bytes).digest()
        return [_WORDS[b % len(_WORDS)] for b in digest[:6]]


def fresh_recovery_phrase(*, n_words: int = 24) -> list[str]:
    return [secrets.choice(_WORDS) for _ in range(n_words)]


def derive_shared_key(local: X25519PrivateKey, peer_pub_bytes: bytes) -> bytes:
    peer_pub = X25519PublicKey.from_public_bytes(peer_pub_bytes)
    return local.exchange(peer_pub)
