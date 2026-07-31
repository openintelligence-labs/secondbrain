"""Shared pytest fixtures.

The LLM swap-ins mutate module-level globals, so any test running a daemon with
`enable_llm=True` would leak LLM-backed extractors into every test after it.
The autouse fixture below restores the heuristic baselines so ordering never
matters — do not remove it.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_llm_swap_ins():
    yield
    from secondbrain.memory.commitments import use_heuristic_extractor
    from secondbrain.memory.digest import use_heuristic_synthesizer
    from secondbrain.memory.importance import use_heuristic_scorer

    use_heuristic_extractor()
    use_heuristic_scorer()
    use_heuristic_synthesizer()
