"""Capture → MaRS-typed MemoryNode extractor.

Turns every Capture into MemoryNodes typed `episodic`, `semantic`,
`procedural`, or `commitment`. Only `episodic` is emitted today.

Every node carries `sources=[capture_id]` so `memory.forget` cascades.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from secondbrain.memory.importance import score as importance_score
from secondbrain.models import Capture

MemoryType = Literal["episodic", "semantic", "procedural", "commitment"]


@dataclass
class ExtractedMemory:
    id: str
    type: MemoryType
    content: str
    valid_from: datetime
    valid_to: datetime | None
    ingested_at: datetime
    importance: float
    sources: list[str]
    persons: list[str] = field(default_factory=list)


# Heuristic person-mention extractor (LLM-backed later).
_NAME_RE = re.compile(r"\b([A-Z][a-z]{2,15})(?:\s+([A-Z][a-z]{2,15}))?\b")
_STOPWORD_NAMES = {
    "Snowflake",
    "Kafka",
    "Stripe",
    "Slack",
    "Notion",
    "Linear",
    "Jira",
    "Datadog",
    "Github",
    "Github.com",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
    "Apple",
    "Apple.com",
}


def _candidate_names(text: str) -> list[str]:
    seen: list[str] = []
    for first, last in _NAME_RE.findall(text):
        full = f"{first} {last}".strip()
        if full in _STOPWORD_NAMES or first in _STOPWORD_NAMES:
            continue
        if full not in seen:
            seen.append(full)
    return seen


def extract(capture: Capture, *, importance_floor: float = 1.0) -> ExtractedMemory | None:
    """Convert a single Capture into one episodic MemoryNode (or None if dull)."""
    text = (capture.ax_text or capture.ocr_text or "").strip()
    if not text:
        return None
    imp = importance_score(text)
    if imp < importance_floor:
        return None
    captured_at = capture.captured_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    return ExtractedMemory(
        id=uuid4().hex,
        type="episodic",
        content=text,
        valid_from=captured_at,
        valid_to=None,
        ingested_at=datetime.now(UTC),
        importance=imp,
        sources=[capture.id],
        persons=_candidate_names(text),
    )
