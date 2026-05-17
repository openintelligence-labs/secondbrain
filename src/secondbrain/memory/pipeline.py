"""Memory pipeline — Capture → extract → A-MEM link → KG insert.

Wires the extractor, importance scorer, A-MEM linker, and entity resolver
into one entry point the daemon can call once per persisted capture.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import structlog

from secondbrain.memory.amem import AMemLinker, now
from secondbrain.memory.clean import content_hash, looks_substantive, strip_chrome
from secondbrain.memory.commitments import extract as extract_commitments
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.extract import ExtractedMemory, extract
from secondbrain.models import Capture
from secondbrain.store.kg import KnowledgeGraph

log = structlog.get_logger()


@dataclass
class PipelineMetrics:
    """Degradation counters surfaced via /metrics. A non-zero count means the
    pipeline successfully ingested the memory but had to skip a step — useful
    for spotting a flaky LLM extractor or a corrupt linker index."""

    linker_failures: int = 0
    commitment_failures: int = 0
    dropped_chrome: int = 0  # text became empty after strip_chrome
    dropped_thin: int = 0  # didn't pass looks_substantive
    dropped_dup_ocr: int = 0  # identical to a recent capture's content

    def as_dict(self) -> dict[str, int]:
        return {
            "linker_failures": self.linker_failures,
            "commitment_failures": self.commitment_failures,
            "dropped_chrome": self.dropped_chrome,
            "dropped_thin": self.dropped_thin,
            "dropped_dup_ocr": self.dropped_dup_ocr,
        }


@dataclass
class MemoryPipeline:
    kg: KnowledgeGraph
    linker: AMemLinker
    resolver: EntityResolver
    # Last N memories to consider as A-MEM neighbors per ingest.
    neighbor_window: int = 200
    # Dedup window: if a capture's cleaned-OCR hash matches anything in the
    # last `ocr_dedup_window` ingests, skip it.
    ocr_dedup_window: int = 50
    metrics: PipelineMetrics = field(default_factory=PipelineMetrics)
    _recent: list[tuple[str, str]] = None  # type: ignore[assignment]
    _recent_ocr_hashes: deque = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._recent is None:
            self._recent = []
        if self._recent_ocr_hashes is None:
            self._recent_ocr_hashes = deque(maxlen=self.ocr_dedup_window)

    def ingest(self, capture: Capture) -> ExtractedMemory | None:
        # Pre-clean: strip menu-bar chrome and OS clock noise from OCR text
        # before extraction. This both improves importance scoring and makes
        # the dedup hash stable across cosmetic frame jitter.
        raw_text = capture.ax_text or capture.ocr_text or ""
        if raw_text:
            cleaned = strip_chrome(raw_text)
            if not cleaned:
                self.metrics.dropped_chrome += 1
                return None
            if not looks_substantive(cleaned):
                self.metrics.dropped_thin += 1
                return None
            # Cross-capture dedup: if we just ingested the same content,
            # don't ingest it again. The cascade already dedups *pixels*,
            # but OCR can produce the same text from visually different
            # frames (cursor blink, sub-pixel scroll, anti-aliasing jitter).
            h = content_hash(cleaned)
            if h in self._recent_ocr_hashes:
                self.metrics.dropped_dup_ocr += 1
                return None
            self._recent_ocr_hashes.append(h)
            # Substitute the cleaned text into the capture so downstream
            # extract / importance / commitment all see the clean version.
            # We mutate ocr_text (not ax_text) because ax_text is treated as
            # canonical structured AX output and shouldn't be silently rewritten.
            if capture.ax_text:
                capture = capture.model_copy(update={"ax_text": cleaned})
            else:
                capture = capture.model_copy(update={"ocr_text": cleaned})

        memory = extract(capture)
        if memory is None:
            return None

        # 1. Persist the capture node + the memory + provenance
        self.kg.upsert_capture(
            capture.id,
            capture.source,
            capture.captured_at,
            capture.app_name,
            capture.app_bundle_id,
        )
        self.kg.upsert_memory(
            memory.id,
            memory.type,
            memory.content,
            valid_from=memory.valid_from,
            valid_to=memory.valid_to,
            ingested_at=memory.ingested_at,
            importance=memory.importance,
        )
        self.kg.link_memory_to_capture(memory.id, capture.id, ingested_at=memory.ingested_at)

        # 2. Resolve persons + add MENTIONS edges
        for name in memory.persons:
            person_id = self.resolver.resolve_from_text(memory.content, default_name=name)
            self.kg.link_memory_to_person(
                memory.id,
                person_id,
                valid_from=memory.valid_from,
                ingested_at=memory.ingested_at,
            )

        # 3. A-MEM neighbor linking. Linker failures are non-fatal — we log
        #    them, bump a counter, and ingest the memory without neighbor edges.
        if self._recent:
            try:
                neighbors = self.linker.neighbors(memory.content, self._recent)
            except Exception as e:
                self.metrics.linker_failures += 1
                log.warning(
                    "memory.linker_failed",
                    memory_id=memory.id,
                    capture_id=capture.id,
                    err=repr(e),
                )
                neighbors = []
            for nid, weight in neighbors:
                self.kg.link_memories(memory.id, nid, weight=weight, ingested_at=now())

        # 4. Update the rolling window
        self._recent.append((memory.id, memory.content))
        if len(self._recent) > self.neighbor_window:
            self._recent = self._recent[-self.neighbor_window :]

        # 5. Commitment extraction. Owner defaults to the first MENTIONS person
        #    (best heuristic without explicit speaker attribution); when no
        #    person was extracted we leave owner_pid empty.
        owner_pid: str | None = None
        if memory.persons:
            owner_pid = self.resolver.resolve_from_text(
                memory.content, default_name=memory.persons[0]
            )
        try:
            # `now` is the capture's own clock, not wall-clock-when-we-ingest.
            # "Sam said tomorrow" should resolve relative to when Sam said it.
            for c in extract_commitments(
                memory.content,
                capture_id=capture.id,
                owner_pid=owner_pid,
                now=capture.captured_at,
            ):
                self.kg.upsert_commitment(
                    c.id,
                    c.content,
                    owner_pid=c.owner_pid,
                    due_at=c.due_at,
                    valid_from=c.valid_from or memory.ingested_at,
                    ingested_at=memory.ingested_at,
                    status=c.status,
                )
        except Exception as e:
            # Don't let a flaky LLM extractor block ingestion. Log + count so
            # the operator can spot a degraded provider via /metrics.
            self.metrics.commitment_failures += 1
            log.warning(
                "memory.commitment_extract_failed",
                memory_id=memory.id,
                capture_id=capture.id,
                err=repr(e),
            )

        return memory
