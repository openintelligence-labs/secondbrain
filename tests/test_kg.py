from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from secondbrain.embed.stub import StubEmbedder
from secondbrain.memory.amem import AMemLinker
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.extract import extract
from secondbrain.memory.pipeline import MemoryPipeline
from secondbrain.models import Capture
from secondbrain.store.kg import KnowledgeGraph


def _cap(cid: str, text: str, when: datetime, app: str = "Slack") -> Capture:
    return Capture(
        id=cid,
        captured_at=when,
        app_name=app,
        app_bundle_id=f"com.example.{app.lower()}",
        ax_text=text,
    )


def _build_pipeline(tmp_path: Path) -> tuple[KnowledgeGraph, MemoryPipeline]:
    kg = KnowledgeGraph(db_path=tmp_path / "kg")
    linker = AMemLinker(embedder=StubEmbedder())
    resolver = EntityResolver(kg=kg)
    return kg, MemoryPipeline(kg=kg, linker=linker, resolver=resolver)


def test_extractor_picks_up_persons_and_importance():
    cap = _cap(
        "c1",
        "Sam Reed said the Snowflake migration deadline is Friday and we will "
        "ship the demo at 9am on Tuesday.",
        datetime(2026, 5, 5, 14, 0, tzinfo=timezone.utc),
    )
    mem = extract(cap)
    assert mem is not None
    assert mem.type == "episodic"
    assert "Sam Reed" in mem.persons
    assert mem.importance >= 3.0
    assert "c1" in mem.sources


def test_pipeline_inserts_provenance_and_persons(tmp_path: Path):
    kg, pipe = _build_pipeline(tmp_path)
    when = datetime(2026, 5, 5, 14, 0, tzinfo=timezone.utc)
    cap = _cap("c1", "Sam Reed will email approvals tomorrow about Snowflake.", when)
    mem = pipe.ingest(cap)
    assert mem is not None
    facts = kg.facts_about(
        kg.find_person_by_alias_or_default("Sam Reed") if False else _person(kg)
    )
    assert any("Snowflake" in f["content"] for f in facts)


def _person(kg: KnowledgeGraph) -> str:
    """Fetch the only Person in the KG (test helper)."""
    r = kg._conn.execute("MATCH (p:Person) RETURN p.id LIMIT 1")
    assert r.has_next()
    return r.get_next()[0]


def test_amem_links_similar_memories(tmp_path: Path):
    kg, pipe = _build_pipeline(tmp_path)
    base = datetime(2026, 5, 5, tzinfo=timezone.utc)
    pipe.ingest(
        _cap("a", "Snowflake migration kickoff with Sam Reed about budget.", base)
    )
    pipe.ingest(
        _cap("b", "Snowflake budget review with Sam Reed Q3 numbers.", base + timedelta(hours=1))
    )
    # The two memories should be linked via LINKED_TO
    r = kg._conn.execute("MATCH (a:MemoryNode)-[l:LINKED_TO]->(b:MemoryNode) RETURN count(*)")
    count = r.get_next()[0]
    assert count >= 1


def test_bi_temporal_facts_about_as_of(tmp_path: Path):
    kg, pipe = _build_pipeline(tmp_path)
    t1 = datetime(2026, 5, 5, tzinfo=timezone.utc)
    t2 = datetime(2026, 5, 6, tzinfo=timezone.utc)
    pipe.ingest(_cap("c1", "Sam Reed leads the Snowflake migration.", t1))
    pipe.ingest(_cap("c2", "Sam Reed handed off Snowflake to Pat Lane.", t2))
    pid = _person(kg)
    full = kg.facts_about(pid)
    assert len(full) >= 2
    as_of_t1 = kg.facts_about(pid, as_of=t1 + timedelta(hours=1))
    # Only the t1 fact should show — t2 fact's valid_from is later.
    assert all(f["valid_from"] <= t1 + timedelta(hours=1) for f in as_of_t1)


def test_forget_capture_cascades(tmp_path: Path):
    kg, pipe = _build_pipeline(tmp_path)
    base = datetime(2026, 5, 5, tzinfo=timezone.utc)
    pipe.ingest(
        _cap("c-keep", "Snowflake review with Sam Reed cost details.", base)
    )
    pipe.ingest(
        _cap("c-forget", "Banking PIN reminder for Sam Reed.", base + timedelta(seconds=1))
    )
    deleted = kg.forget_capture("c-forget")
    assert deleted == 1
    # Captures table now has only one capture
    r = kg._conn.execute("MATCH (c:Capture) RETURN count(*)")
    assert r.get_next()[0] == 1
