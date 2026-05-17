from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from secondbrain.embed.stub import StubEmbedder
from secondbrain.memory.amem import AMemLinker
from secondbrain.memory.commitments import (
    Commitment,
    heuristic_extract,
    is_broken,
)
from secondbrain.memory.decay import decay_factor, half_life_days
from secondbrain.memory.digest import render
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.pipeline import MemoryPipeline
from secondbrain.memory.scheduler import (
    SchedulerConfig,
    SchedulerState,
    should_fire,
)
from secondbrain.models import Capture
from secondbrain.store.kg import KnowledgeGraph


def test_commitment_detect_friday():
    now = datetime(2026, 5, 5, 14, 0, tzinfo=UTC)  # Tuesday
    out = heuristic_extract(
        "I'll send the design doc by Friday. Sam will review tomorrow.",
        capture_id="c1",
        now=now,
    )
    assert len(out) == 2
    assert all("c1" in c.sources for c in out)
    fri = next(c for c in out if "design doc" in c.content)
    assert fri.due_at is not None
    assert fri.due_at.weekday() == 4  # Friday


def test_is_broken_only_for_open_past_due():
    past = Commitment(
        id="x",
        content="...",
        owner_pid=None,
        due_at=datetime(2026, 5, 1, tzinfo=UTC),
        status="open",
    )
    closed = Commitment(
        id="y",
        content="...",
        owner_pid=None,
        due_at=datetime(2026, 5, 1, tzinfo=UTC),
        status="done",
    )
    now = datetime(2026, 5, 5, tzinfo=UTC)
    assert is_broken(past, now=now) is True
    assert is_broken(closed, now=now) is False


def test_decay_high_importance_decays_slower():
    ingested = datetime(2026, 5, 1, tzinfo=UTC)
    now = datetime(2026, 5, 6, tzinfo=UTC)
    high = decay_factor(ingested_at=ingested, importance=8.0, now=now)
    low = decay_factor(ingested_at=ingested, importance=1.0, now=now)
    assert high > low
    assert half_life_days(8.0) > half_life_days(1.0)


def test_scheduler_token_threshold_fires():
    cfg = SchedulerConfig(token_budget=100, token_fraction_trigger=0.6)
    state = SchedulerState(token_count=70)
    fire, reason = should_fire(state, cfg)
    assert fire is True
    assert reason == "token_threshold"


def test_scheduler_idle_fires():
    state = SchedulerState(last_input_ts=0.0)  # forever ago
    fire, reason = should_fire(state)
    assert fire is True
    assert reason.startswith("idle")


def test_digest_groups_themes_and_broken_promises(tmp_path: Path):
    kg = KnowledgeGraph(db_path=tmp_path / "kg")
    pipe = MemoryPipeline(
        kg=kg,
        linker=AMemLinker(embedder=StubEmbedder()),
        resolver=EntityResolver(kg=kg),
    )
    today = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    pipe.ingest(
        Capture(
            id="c1",
            captured_at=today,
            app_name="Slack",
            ax_text="Sam Reed will ship the Snowflake migration by Friday.",
        )
    )
    pipe.ingest(
        Capture(
            id="c2",
            captured_at=today + timedelta(hours=1),
            app_name="Linear",
            ax_text="Stripe billing token expiry deadline review on Wednesday.",
        )
    )
    open_promise = Commitment(
        id="p1",
        content="I'll send the deck by Monday.",
        owner_pid=None,
        due_at=today - timedelta(days=2),
        status="open",
        sources=["c1"],
    )
    digest = render(
        kg,
        "day",
        day=today.date(),
        open_commitments=[open_promise],
        now=today,
    )
    assert digest.period == "day"
    assert digest.period_start == today.date()
    assert any("snowflake" in t.lower() for t in digest.themes)
    assert "I'll send the deck by Monday." in digest.broken_promises
    assert digest.cited_memories  # non-empty
