"""Commitment extractor.

Detects first-person promises ("I'll send you the doc by Friday", "we'll
deploy on Tuesday") and emits typed `Commitment` records. Heuristic regex
baseline; LLM swap-in over `set_extractor()` later.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4


@dataclass
class Commitment:
    id: str
    content: str
    owner_pid: str | None
    due_at: datetime | None
    status: str = "open"
    valid_from: datetime | None = None
    sources: list[str] = field(default_factory=list)


_PROMISE_RE = re.compile(
    r"\b("
    r"i('| wi)?ll\s+|"
    r"we('| wi)?ll\s+|"
    r"i'?m\s+going\s+to\s+|"
    r"we're\s+going\s+to\s+|"
    r"i\s+plan\s+to\s+|"
    r"will\s+(send|do|review|ship|deploy|email|share|file|finish|hand)\b"
    r")",
    re.IGNORECASE,
)

_DAY_RE = re.compile(
    r"\b(?:by\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|today)\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _parse_due(text: str, *, now: datetime) -> datetime | None:
    m = _DATE_RE.search(text)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
    m = _DAY_RE.search(text)
    if not m:
        return None
    word = m.group(1).lower()
    if word == "today":
        return datetime.combine(now.date(), time(17, 0), tzinfo=UTC)
    if word == "tonight":
        return datetime.combine(now.date(), time(20, 0), tzinfo=UTC)
    if word == "tomorrow":
        return datetime.combine(now.date() + timedelta(days=1), time(17, 0), tzinfo=UTC)
    target = _DAY_NAMES[word]
    delta = (target - now.weekday()) % 7
    if delta == 0:
        delta = 7
    return datetime.combine(now.date() + timedelta(days=delta), time(17, 0), tzinfo=UTC)


def heuristic_extract(
    text: str,
    *,
    capture_id: str,
    owner_pid: str | None = None,
    now: datetime | None = None,
) -> list[Commitment]:
    if not text:
        return []
    now = now or datetime.now(UTC)
    out: list[Commitment] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if not _PROMISE_RE.search(sentence):
            continue
        out.append(
            Commitment(
                id=uuid4().hex,
                content=sentence.strip(),
                owner_pid=owner_pid,
                due_at=_parse_due(sentence, now=now),
                valid_from=now,
                sources=[capture_id],
            )
        )
    return out


_extractor: Callable[..., list[Commitment]] = heuristic_extract


def set_extractor(fn: Callable[..., list[Commitment]]) -> None:
    global _extractor
    _extractor = fn


import asyncio as _asyncio  # noqa: E402  (avoid shadowing top-of-file imports)
import threading as _threading  # noqa: E402

from pydantic import BaseModel as _BaseModel  # noqa: E402
from pydantic import Field as _Field  # noqa: E402


def _run_blocking(coro):
    """Run a coroutine to completion from sync code, even when an event loop
    is already running on the caller's thread (e.g. inside the daemon)."""
    try:
        _asyncio.get_running_loop()
    except RuntimeError:
        return _asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_asyncio.run, coro).result()


class _LLMCommitment(_BaseModel):
    """One commitment as the LLM sees it."""

    sentence: str = _Field(description="The exact sentence committing to the action.")
    due_iso: str | None = _Field(
        default=None,
        description="ISO 8601 datetime if a due time can be inferred, else null.",
    )


class _LLMCommitments(_BaseModel):
    items: list[_LLMCommitment] = _Field(default_factory=list)


_LLM_PROMPT = (
    "Identify first-person promises or commitments in the snippet below. "
    "A commitment is any sentence where the speaker says they will do "
    "something, with or without a deadline. Skip questions, observations, "
    "and statements about other people's actions unless they're clearly "
    'agreed to ("we will", "I\'ll").\n\n'
    "If you find a deadline, render it as ISO 8601 (YYYY-MM-DDTHH:MM:SS). "
    'Use the implied year of {year} for any "Friday" / "tomorrow" phrasings; '
    "if no deadline is mentioned, return null.\n\n"
    "Snippet:\n{text}"
)


class _ActantsExtractor:
    def __init__(self, *, model: str | None = None, timeout_s: float = 8.0) -> None:
        self._model = model
        self._timeout_s = timeout_s
        self._llm = None
        self._lock = _threading.Lock()

    def _ensure_llm(self):
        if self._llm is not None:
            return self._llm
        with self._lock:
            if self._llm is None:
                from actants import LLM

                self._llm = LLM(model=self._model) if self._model else LLM()
        return self._llm

    def __call__(
        self,
        text: str,
        *,
        capture_id: str,
        owner_pid: str | None = None,
        now: datetime | None = None,
    ) -> list[Commitment]:
        if not text or not text.strip():
            return []
        now = now or datetime.now(UTC)
        llm = self._ensure_llm()

        prompt = _LLM_PROMPT.format(text=text, year=now.year)

        async def _go():
            return await _asyncio.wait_for(
                llm.extract(prompt, _LLMCommitments, temperature=0.0),
                timeout=self._timeout_s,
            )

        try:
            result = _run_blocking(_go())
        except Exception:
            return heuristic_extract(text, capture_id=capture_id, owner_pid=owner_pid, now=now)

        out: list[Commitment] = []
        for item in result.items:
            due: datetime | None = None
            if item.due_iso:
                try:
                    due = datetime.fromisoformat(item.due_iso.replace("Z", "+00:00"))
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=UTC)
                except (TypeError, ValueError):
                    due = None
            out.append(
                Commitment(
                    id=uuid4().hex,
                    content=item.sentence.strip(),
                    owner_pid=owner_pid,
                    due_at=due,
                    valid_from=now,
                    sources=[capture_id],
                )
            )
        return out


def use_actants_extractor(*, model: str | None = None, timeout_s: float = 8.0) -> None:
    """Flip commitment extraction to call an LLM via actants. Falls back on error."""
    set_extractor(_ActantsExtractor(model=model, timeout_s=timeout_s))


def use_heuristic_extractor() -> None:
    """Reset to the regex baseline (default)."""
    set_extractor(heuristic_extract)


def extract(*args, **kwargs) -> list[Commitment]:
    return _extractor(*args, **kwargs)


def is_broken(c: Commitment, *, now: datetime) -> bool:
    return c.status == "open" and c.due_at is not None and c.due_at < now
