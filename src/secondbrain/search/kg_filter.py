"""KG-prefiltered hybrid retrieval.

When the user query mentions a known entity (a Person.name we have in the KG),
constrain the candidate set to captures that produced MemoryNodes mentioning
that person. Falls back to plain hybrid when no entity hit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from secondbrain.search.hybrid import HybridSearcher, HybridHit
from secondbrain.store.kg import KnowledgeGraph


_PERSON_NAME = re.compile(r"\b([A-Z][a-z]{2,15}(?:\s+[A-Z][a-z]{2,15})?)\b")


def find_person_in_query(query: str, kg: KnowledgeGraph) -> str | None:
    for cand in _PERSON_NAME.findall(query):
        slug = re.sub(r"[^a-z0-9]+", "_", cand.lower()).strip("_")
        pid = f"person:{slug}"
        r = kg._conn.execute(
            "MATCH (p:Person {id:$id}) RETURN p.id LIMIT 1", {"id": pid}
        )
        if r.has_next():
            return pid
    return None


def captures_mentioning(kg: KnowledgeGraph, person_id: str) -> set[str]:
    r = kg._conn.execute(
        "MATCH (m:MemoryNode)-[:MENTIONS]->(p:Person {id:$pid}), "
        "(m)-[:DERIVED_FROM]->(c:Capture) "
        "RETURN DISTINCT c.id",
        {"pid": person_id},
    )
    out: set[str] = set()
    while r.has_next():
        out.add(r.get_next()[0])
    return out


@dataclass
class KGAwareSearcher:
    kg: KnowledgeGraph
    inner: HybridSearcher

    def search(self, query: str, *, limit: int = 10) -> list[HybridHit]:
        hits = self.inner.search(query, limit=max(limit * 4, 50))
        person = find_person_in_query(query, self.kg)
        if person is None:
            return hits[:limit]
        allowed = captures_mentioning(self.kg, person)
        if not allowed:
            return hits[:limit]
        filtered = [h for h in hits if h.capture_id in allowed]
        return filtered[:limit]
