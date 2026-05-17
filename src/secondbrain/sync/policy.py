"""Sync policy.

The architecture's locked contract:
  - structured facts and dense embeddings sync ✅
  - raw HEVC frames and audio NEVER sync ❌
  - per-device-class overrides allowed (phone, laptop, tablet, regulated)

This module owns the *what may leave a device* decision. Backends call
`should_sync(item)` before sending and refuse anything that returns False.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class DeviceClass(StrEnum):
    LAPTOP = "laptop"
    PHONE = "phone"
    TABLET = "tablet"
    REGULATED = "regulated"  # locked-down work device — never sends


SyncableKind = Literal[
    "memory_node",  # MaRS node body
    "kg_edge",  # KG relations
    "person_alias",  # Person/Alias graph
    "commitment",  # commitment node
    "dense_embedding",  # 768-d Nomic vector
    "audit_log_entry",
    # never-sync (deny by default):
    "hevc_frame",
    "audio_chunk",
    "ocr_text",  # raw OCR can include sensitive screen content
]

ALLOWED_BY_DEFAULT: set[SyncableKind] = {
    "memory_node",
    "kg_edge",
    "person_alias",
    "commitment",
    "dense_embedding",
    "audit_log_entry",
}


@dataclass
class SyncPolicy:
    device_class: DeviceClass = DeviceClass.LAPTOP
    extra_allow: set[SyncableKind] | None = None
    extra_deny: set[SyncableKind] | None = None

    def should_sync(self, kind: SyncableKind) -> bool:
        if self.device_class is DeviceClass.REGULATED:
            return False
        deny = self.extra_deny or set()
        if kind in deny:
            return False
        allow = (self.extra_allow or set()) | ALLOWED_BY_DEFAULT
        return kind in allow
