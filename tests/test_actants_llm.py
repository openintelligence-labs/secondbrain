"""H-06 — LLM-in-the-loop tests through actants.

These tests skip when Ollama isn't reachable. When it is, they exercise the
real call path through `actants.LLM` / `actants.Embeddings` for the four
swap-in points wired in H-02..H-05:

    1. Embeddings via actants → LanceDB write + cosine search
    2. Importance scorer (LLM) returns sane numeric range
    3. Commitment extractor (LLM, Pydantic structured output) finds a known
       commitment in a fixture sentence
    4. Digest synthesizer (LLM) produces non-keyword themes

The fallback paths inside each call mean a flaky LLM doesn't break tests —
but a healthy LLM should still produce LLM-like (not heuristic-shaped) output.
"""

from __future__ import annotations

import os
import urllib.request
from datetime import UTC

import pytest


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


_PRECONDITION = pytest.mark.skipif(
    not _ollama_up() or os.environ.get("SECONDBRAIN_SKIP_LLM_TESTS") == "1",
    reason="Ollama not reachable on localhost:11434, or SECONDBRAIN_SKIP_LLM_TESTS=1",
)


# Default chat model: gpt-oss:20b-cloud is small, structured-output-capable,
# and reachable via the same Ollama endpoint. Override with the env var to
# point at any local Ollama-served chat model.
_CHAT_MODEL = os.environ.get("SECONDBRAIN_TEST_CHAT_MODEL", "gpt-oss:20b-cloud")
_EMBED_MODEL = os.environ.get("SECONDBRAIN_TEST_EMBED_MODEL", "nomic-embed-text")


@_PRECONDITION
def test_actants_embedder_round_trip():
    from secondbrain.embed.text import TextEmbedder

    embedder = TextEmbedder.via_actants(model=_EMBED_MODEL)
    vec_a = embedder.embed_query("snowflake migration deadline")
    vec_b = embedder.embed_query("kafka pipeline outage")
    # Real embeddings: same prompt should embed close to itself, different
    # prompts should embed further apart.
    import numpy as np

    same = float(np.dot(vec_a, embedder.embed_query("snowflake migration deadline")))
    diff = float(np.dot(vec_a, vec_b))
    assert same > 0.95, f"same-text similarity unexpectedly low: {same}"
    assert diff < same, f"diff-text >= same-text: same={same} diff={diff}"


@_PRECONDITION
def test_actants_importance_scorer_returns_in_range():
    from secondbrain.memory.importance import (
        score,
        use_actants_scorer,
        use_heuristic_scorer,
    )

    use_actants_scorer(model=_CHAT_MODEL, timeout_s=30.0)
    try:
        critical = score("Sam will ship the Snowflake migration by Friday or we miss launch.")
        trivial = score("a")
        assert 0.0 <= critical <= 10.0
        assert 0.0 <= trivial <= 10.0
        # A real LLM, given a clearly-critical commitment, should rate it
        # higher than a one-character no-content snippet. If the LLM
        # disagrees, the test fails — this is the whole point of running it.
        assert critical >= trivial
    finally:
        use_heuristic_scorer()


@_PRECONDITION
def test_actants_commitment_extractor_finds_first_person_promise():
    from datetime import datetime

    from secondbrain.memory.commitments import (
        extract,
        use_actants_extractor,
        use_heuristic_extractor,
    )

    use_actants_extractor(model=_CHAT_MODEL, timeout_s=45.0)
    try:
        out = extract(
            "I'll send the Snowflake design doc by Friday. "
            "Pat is responsible for the rollback plan.",
            capture_id="c-test",
            now=datetime(2026, 5, 6, 12, 0, tzinfo=UTC),
        )
        # The LLM should at minimum find the first-person commitment.
        # The second sentence is about Pat (third person) — fine if it's
        # included or excluded.
        assert len(out) >= 1
        assert any("send" in c.content.lower() or "design doc" in c.content.lower() for c in out)
    finally:
        use_heuristic_extractor()


@_PRECONDITION
def test_actants_digest_synthesizer_produces_prose_themes():
    from secondbrain.memory.digest import (
        heuristic_synthesize,
        use_actants_synthesizer,
        use_heuristic_synthesizer,
    )

    memories = [
        {"content": "Sam Reed will ship the Snowflake migration by Friday.", "importance": 8.5},
        {"content": "Kafka consumer lag spiked at 14:02 — investigating.", "importance": 6.0},
        {"content": "Stripe billing token expiry hotfix needed Wednesday.", "importance": 7.0},
    ]

    use_actants_synthesizer(model=_CHAT_MODEL, timeout_s=60.0)
    try:
        themes, followups = (
            heuristic_synthesize(memories)
            if False
            else __import__("secondbrain.memory.digest", fromlist=["_synthesizer"])._synthesizer(
                memories
            )
        )
        # Themes should look like prose phrases, not single keywords. The
        # heuristic produces strings like "snowflake (1)" — the LLM should
        # produce something with spaces and varied vocabulary.
        assert len(themes) >= 1
        if themes:
            # Heuristic outputs match `^\w+ \(\d+\)$`. The LLM shouldn't.
            import re

            heuristic_shape = re.compile(r"^\S+ \(\d+\)$")
            assert not all(heuristic_shape.match(t) for t in themes), (
                f"themes look like the heuristic's output, not LLM prose: {themes}"
            )
    finally:
        use_heuristic_synthesizer()
