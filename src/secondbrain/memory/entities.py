"""Cross-app entity resolution.

The architecture's full version layers face embeddings (insightface),
voiceprints (ECAPA, shared with MeetMind), email/handle aliasing, and
calendar-attendee priors. Today we ship the alias path: a Person record
plus a HAS_ALIAS edge for every observed email/handle/calendar-name.

Faces and voiceprints plug in at the same `EntityResolver` API once those
capture sources land.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from secondbrain.store.kg import KnowledgeGraph

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _stable_id(name: str) -> str:
    """Stable id derived from the canonical name only.

    This is sufficient today; once we have face/voice we'll move to
    embedding-based clustering and re-key when confidence is high.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"person:{slug}"


@dataclass
class EntityResolver:
    kg: KnowledgeGraph

    def resolve_or_create_person(
        self,
        name: str,
        email: str | None = None,
        handle: str | None = None,
    ) -> str:
        """Return a Person id, creating + aliasing as needed."""
        # 1. Existing alias?
        for alias in (email, handle):
            if alias:
                hit = self.kg.find_person_by_alias(alias)
                if hit:
                    return hit
        # 2. Existing name-derived person?
        person_id = _stable_id(name)
        existing = self.kg._conn.execute(
            "MATCH (p:Person {id:$id}) RETURN count(p)", {"id": person_id}
        )
        if existing.get_next()[0] == 0:
            self.kg.upsert_person(person_id, name=name, primary_email=email)
        if email:
            # Alias check is internal to add_alias's idempotence guard.
            if not self.kg.find_person_by_alias(email):
                self.kg.add_alias(person_id, email, "email")
        if handle and not self.kg.find_person_by_alias(handle):
            self.kg.add_alias(person_id, handle, "handle")
        return person_id

    def resolve_from_text(self, text: str, *, default_name: str) -> str:
        """When text contains an email, link the address to a Person named
        `default_name` (typical for "Sam said: foo" + we already know Sam's
        email is foo@). This is a useful baseline; the LLM-typed extractor
        will eventually produce richer hints.
        """
        emails = EMAIL_RE.findall(text)
        return self.resolve_or_create_person(
            default_name, email=emails[0] if emails else None
        )
