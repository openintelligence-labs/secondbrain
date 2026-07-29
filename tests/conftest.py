"""Shared pytest fixtures.

The daemon's LLM swap-ins (`use_actants_scorer` / `use_actants_extractor` /
`use_actants_synthesizer`) mutate module-level globals. Any test that stands up
a daemon with `enable_llm=True` (e.g. test_daemon_llm.py, which runs whenever
Ollama is reachable) would otherwise leak the LLM-backed extractors into every
test that runs after it — the heuristic-only HTTP gateway tests included.
Reset the globals around every test so ordering never matters.
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
