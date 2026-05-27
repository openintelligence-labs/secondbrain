"""Importance scorer.

Two implementations:

  - `heuristic_importance` — regex+length baseline, sub-millisecond, no I/O.
    The default. Used by every test and by every code path until you flip
    over.

  - `_ActantsScorer` — routes through `actants.LLM.extract` (Pydantic
    structured output), asks an LLM (Ollama-default per actants config) to
    rate the text 0..10. Costs one LLM call per scored event; ~100–500ms
    on a local Phi-4-mini.

Wire the LLM path with:

    from secondbrain.memory.importance import use_actants_scorer
    use_actants_scorer()                # uses default actants LLM
    use_actants_scorer(model="phi4-mini")
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Callable

from pydantic import BaseModel, Field

# Things that often carry importance in a knowledge-worker workflow.
HIGH_SIGNAL = re.compile(
    r"\b("
    r"deadline|due|by\s+(monday|tuesday|wednesday|thursday|friday|tomorrow)|"
    r"action|todo|will\s+(send|do|review|ship|deploy|email)|"
    r"decision|approve|launch|hire|fire|"
    r"meeting|call|standup|1:1|interview|"
    r"snowflake|stripe|kafka|aws|gcp|"
    r"\$\d|"
    r"@\w+|#\w+"
    r")\b",
    re.IGNORECASE,
)


def heuristic_importance(text: str) -> float:
    """Return a 0..10 score. Cheap and deterministic."""
    if not text:
        return 0.0
    n_signal = len(HIGH_SIGNAL.findall(text))
    length_score = min(len(text) / 400.0, 2.0)  # up to 2 points for length
    signal_score = min(n_signal * 1.5, 6.0)  # up to 6 points for content
    base = 1.0 if text.strip() else 0.0
    return round(min(base + length_score + signal_score, 10.0), 2)


# ----- actants-backed LLM scorer -----------------------------------------


class _ImportanceJudgement(BaseModel):
    """Pydantic schema for `LLM.extract` so we get a clean float back."""

    importance: float = Field(
        ge=0.0,
        le=10.0,
        description="0..10 importance for personal-memory recall later.",
    )
    reason: str = Field(
        default="",
        description="One sentence on why this matters or doesn't.",
    )


_PROMPT = (
    "You score how much a given snippet of captured screen text matters for "
    "personal memory recall. 0 = trivial UI noise. 5 = useful background. "
    "10 = critical (commitments, decisions, deadlines, named-person mentions).\n\n"
    "Snippet: {text}"
)


class _ActantsScorer:
    def __init__(self, *, model: str | None = None, timeout_s: float = 5.0) -> None:
        self._model = model
        self._timeout_s = timeout_s
        self._llm = None
        self._lock = threading.Lock()

    def _ensure_llm(self):
        if self._llm is not None:
            return self._llm
        with self._lock:
            if self._llm is None:
                from actants import LLM

                self._llm = LLM(model=self._model) if self._model else LLM()
        return self._llm

    def __call__(self, text: str) -> float:
        if not text or not text.strip():
            return 0.0
        llm = self._ensure_llm()

        async def _go():
            return await asyncio.wait_for(
                llm.extract(_PROMPT.format(text=text), _ImportanceJudgement, temperature=0.0),
                timeout=self._timeout_s,
            )

        try:
            verdict = _run_blocking(_go())
            return round(float(verdict.importance), 2)
        except Exception:
            # Don't block ingestion on a flaky LLM — fall back to heuristic.
            return heuristic_importance(text)


def _run_blocking(coro):
    """Run a coroutine to completion from sync code, even when an event loop
    is already running on the caller's thread (e.g. inside the daemon).

    Strategy: if no loop is running, plain `asyncio.run`. Otherwise spin a
    short-lived thread with its own loop. This is the standard pattern for
    library code that wants to expose a sync surface but ride on async I/O.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Caller already has a running loop. Don't fight it; run on a worker.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


_scorer: Callable[[str], float] = heuristic_importance


def set_scorer(fn: Callable[[str], float]) -> None:
    """Swap in any custom scorer at runtime."""
    global _scorer
    _scorer = fn


def use_actants_scorer(*, model: str | None = None, timeout_s: float = 5.0) -> None:
    """Flip `score()` to call an LLM via actants. Falls back to heuristic on error."""
    set_scorer(_ActantsScorer(model=model, timeout_s=timeout_s))


def use_heuristic_scorer() -> None:
    """Reset to the deterministic heuristic baseline (default)."""
    set_scorer(heuristic_importance)


def score(text: str) -> float:
    return _scorer(text)
