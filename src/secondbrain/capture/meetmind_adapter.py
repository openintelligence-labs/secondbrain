"""MeetMind ingestion adapter.

MeetMind ships meetings as a list of `TranscriptSegment` records with
`speaker_id`, `text`, `start_ms`, `end_ms`. We turn each into a
`Capture(source='audio')` so retrieval, KG, and reflection all work
unchanged.

Voiceprints flow through the entity resolver: a MeetMind speaker_id
is treated as an alias kind 'voiceprint' that the resolver can attach to a
Person.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from secondbrain.indexing import Indexer
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.pipeline import MemoryPipeline
from secondbrain.models import Capture


@dataclass
class MeetingIngestionResult:
    captures: int
    persons: list[str]


def ingest_meeting(
    meeting: dict[str, Any],
    *,
    indexer: Indexer,
    pipe: MemoryPipeline,
    resolver: EntityResolver,
) -> MeetingIngestionResult:
    """`meeting` follows the MeetMind public schema.

    Only the bits we need:
        meeting['id']              str
        meeting['started_at']      ISO8601
        meeting['title']           str | None
        meeting['segments']        list of {speaker_id, speaker_name?, text, start_ms, end_ms}
    """
    started = datetime.fromisoformat(meeting["started_at"].replace("Z", "+00:00"))
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    title = meeting.get("title") or "(untitled meeting)"
    persons: list[str] = []

    for seg in meeting.get("segments", []):
        speaker_id = seg.get("speaker_id")
        speaker_name = seg.get("speaker_name") or speaker_id or "speaker"
        offset_ms = int(seg.get("start_ms", 0))
        captured_at = started + timedelta(milliseconds=offset_ms)
        text = seg.get("text", "").strip()
        if not text:
            continue
        cap = Capture(
            id=f"audio:{meeting['id']}:{seg.get('id', offset_ms)}",
            source="audio",
            captured_at=captured_at,
            app_name="MeetMind",
            app_bundle_id="com.openintelligence.meetmind",
            window_title=title,
            ax_text=f"{speaker_name}: {text}",
        )
        indexer.index_capture(cap)
        pipe.ingest(cap)
        if speaker_id:
            pid = resolver.resolve_or_create_person(
                speaker_name, handle=speaker_id
            )
            if pid not in persons:
                persons.append(pid)

    return MeetingIngestionResult(
        captures=sum(1 for s in meeting.get("segments", []) if s.get("text")),
        persons=persons,
    )
