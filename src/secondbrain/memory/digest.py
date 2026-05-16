"""Daily / weekly / monthly digest renderer.

Heuristic synthesis baseline (LLM swap-in via `set_synthesizer`). Reads the
KG's MemoryNodes for the period, surfaces themes (top-importance memories)
plus broken commitments.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Literal

from secondbrain.memory.commitments import Commitment, is_broken
from secondbrain.store.kg import KnowledgeGraph

Period = Literal["day", "week", "month"]


@dataclass
class Digest:
    period: Period
    period_start: date
    themes: list[str]
    broken_promises: list[str]
    suggested_followups: list[str]
    cited_memories: list[str] = field(default_factory=list)
    importance_sum: float = 0.0


def _bounds(period: Period, day: date) -> tuple[datetime, datetime]:
    if period == "day":
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
    elif period == "week":
        start_day = day - timedelta(days=day.weekday())
        start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=7)
    elif period == "month":
        start = datetime.combine(day.replace(day=1), time.min, tzinfo=timezone.utc)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    else:
        raise ValueError(f"unknown period: {period}")
    return start, end


_KEY_TOKENS = {"snowflake", "kafka", "stripe", "ship", "deploy", "review", "deadline"}


def _topic_phrases(content: str) -> list[str]:
    tokens = [t.strip(".,;:!?").lower() for t in content.split()]
    return [t for t in tokens if t in _KEY_TOKENS]


def heuristic_synthesize(memories: list[dict]) -> tuple[list[str], list[str]]:
    """(themes, suggested_followups). LLM swap-in candidate."""
    counter: Counter[str] = Counter()
    for m in memories:
        for tok in _topic_phrases(m["content"]):
            counter[tok] += 1
    themes = [
        f"{w} ({n})"
        for w, n in counter.most_common(5)
    ]
    followups: list[str] = []
    for m in sorted(memories, key=lambda x: x["importance"], reverse=True)[:3]:
        followups.append(m["content"][:120])
    return themes, followups


_synthesizer: Callable[[list[dict]], tuple[list[str], list[str]]] = heuristic_synthesize


def set_synthesizer(fn: Callable[[list[dict]], tuple[list[str], list[str]]]) -> None:
    global _synthesizer
    _synthesizer = fn


# ----- actants-backed LLM synthesizer ------------------------------------

import asyncio as _asyncio  # noqa: E402
import threading as _threading  # noqa: E402

from pydantic import BaseModel as _BaseModel, Field as _Field  # noqa: E402


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


class _DigestSynthesis(_BaseModel):
    """LLM output: themes + follow-ups, both human-readable strings."""
    themes: list[str] = _Field(
        default_factory=list,
        description="3–5 short prose phrases summarizing the day's topics.",
    )
    followups: list[str] = _Field(
        default_factory=list,
        description=(
            "Up to 3 actionable follow-ups, each citing a specific memory "
            "by quoting a short fragment of its content."
        ),
    )


_DIGEST_PROMPT = (
    "You are a Chain-of-Density summarizer for a personal-memory app. "
    "Given the day's memory snippets (most-recent first), produce:\n"
    "- 3–5 themes, each a short prose phrase (NOT keyword tags).\n"
    "- Up to 3 follow-up suggestions the user should act on tomorrow, each "
    "  quoting a specific memory.\n\n"
    "Memories:\n{joined}"
)


class _ActantsSynthesizer:
    def __init__(self, *, model: str | None = None, timeout_s: float = 30.0) -> None:
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

    def __call__(self, memories: list[dict]) -> tuple[list[str], list[str]]:
        if not memories:
            return [], []
        joined = "\n".join(
            f"- [{m.get('importance', 0):.1f}] {m['content']}"
            for m in memories[:60]
        )
        prompt = _DIGEST_PROMPT.format(joined=joined)
        llm = self._ensure_llm()

        async def _go():
            return await _asyncio.wait_for(
                llm.extract(prompt, _DigestSynthesis, temperature=0.3),
                timeout=self._timeout_s,
            )

        try:
            out = _run_blocking(_go())
            return list(out.themes)[:5], list(out.followups)[:3]
        except Exception:
            return heuristic_synthesize(memories)


def use_actants_synthesizer(*, model: str | None = None, timeout_s: float = 30.0) -> None:
    """Flip digest synthesis to call an LLM via actants. Falls back on error."""
    set_synthesizer(_ActantsSynthesizer(model=model, timeout_s=timeout_s))


def use_heuristic_synthesizer() -> None:
    """Reset to the keyword-counter baseline (default)."""
    set_synthesizer(heuristic_synthesize)


def render(
    kg: KnowledgeGraph,
    period: Period,
    *,
    day: date | None = None,
    open_commitments: list[Commitment] | None = None,
    now: datetime | None = None,
) -> Digest:
    day = day or datetime.now(timezone.utc).date()
    start, end = _bounds(period, day)
    memories = kg.events_at(start, end, limit=200)
    themes, followups = _synthesizer(memories)
    now = now or datetime.now(timezone.utc)
    broken = []
    for c in open_commitments or []:
        if is_broken(c, now=now):
            broken.append(c.content)
    importance_sum = float(sum(m["importance"] for m in memories))
    return Digest(
        period=period,
        period_start=start.date(),
        themes=themes,
        broken_promises=broken,
        suggested_followups=followups,
        cited_memories=[m["memory_id"] for m in memories],
        importance_sum=importance_sum,
    )
