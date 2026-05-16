"""Memory pipeline must keep ingesting when sub-components throw.

We assert two paths:
  - A-MEM linker raises → memory still lands in KG, linker_failures bumps.
  - Commitment extractor raises → memory still lands, commitment_failures bumps.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from secondbrain.memory.amem import AMemLinker
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.pipeline import MemoryPipeline
from secondbrain.models import Capture
from secondbrain.store.kg import KnowledgeGraph


def _capture(text: str) -> Capture:
    return Capture(
        id="cap1",
        captured_at=datetime.now(timezone.utc),
        app_name="TestApp",
        app_bundle_id="com.test",
        ax_text=text,
    )


@pytest.fixture
def pipeline(tmp_path: Path) -> MemoryPipeline:
    kg = KnowledgeGraph(db_path=tmp_path / "kg")

    class _StubEmbedder:
        def embed_text(self, _text: str):
            import numpy as np
            return np.zeros(8, dtype="float32")

        def embed_texts(self, texts):
            import numpy as np
            return np.zeros((len(texts), 8), dtype="float32")

    return MemoryPipeline(
        kg=kg,
        linker=AMemLinker(embedder=_StubEmbedder()),
        resolver=EntityResolver(kg=kg),
    )


def test_linker_failure_does_not_block_ingest(pipeline: MemoryPipeline) -> None:
    # Prime _recent so the linker actually gets called on the second ingest.
    pipeline.ingest(_capture("Sam shipped the migration on Friday."))
    assert pipeline.metrics.linker_failures == 0

    with patch.object(pipeline.linker, "neighbors", side_effect=RuntimeError("boom")):
        out = pipeline.ingest(_capture("Linda merged the dashboard branch."))

    assert out is not None
    assert pipeline.metrics.linker_failures == 1


def test_commitment_extractor_failure_does_not_block_ingest(pipeline: MemoryPipeline) -> None:
    with patch(
        "secondbrain.memory.pipeline.extract_commitments",
        side_effect=RuntimeError("LLM timeout"),
    ):
        out = pipeline.ingest(
            _capture("I'll send the brief to Sam by Tuesday.")
        )
    assert out is not None
    assert pipeline.metrics.commitment_failures == 1
