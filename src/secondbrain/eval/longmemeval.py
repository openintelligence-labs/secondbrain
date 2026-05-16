"""LongMemEval harness.

Loads a JSONL of LongMemEval cases (the public dataset format), runs every
case through `HybridSearcher`, and reports a per-axis breakdown plus an
overall accuracy score.

Schema (one line per case):
    {"axis": "extraction"|"multi-session"|"temporal"|"knowledge_update"|"abstention",
     "query": "...",
     "expected_capture_ids": ["..."],
     # optional — when omitted, defaults to a low value so abstention cases
     # treat low rrf_score as "abstain":
     "abstention_score_threshold": 0.005}

Scoring:
  - For non-abstention axes: hit ⇔ at least one expected_capture_id is in
    the top-K. Standard recall-style.
  - For abstention axes: hit ⇔ retriever returns no result whose
    `rrf_score` exceeds the threshold (i.e. the system correctly refused
    to confidently surface an off-topic capture).
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from secondbrain.search.hybrid import HybridSearcher

DEFAULT_ABSTENTION_THRESHOLD = 0.02


@dataclass
class LongMemEvalResult:
    n: int
    overall_accuracy: float
    by_axis: dict[str, float] = field(default_factory=dict)
    misses: list[str] = field(default_factory=list)


def run(
    searcher: HybridSearcher,
    cases_path: Path,
    *,
    k: int = 10,
) -> LongMemEvalResult:
    hits = 0
    total = 0
    axis_totals: dict[str, int] = defaultdict(int)
    axis_hits: dict[str, int] = defaultdict(int)
    misses: list[str] = []

    for line in cases_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        axis = rec.get("axis", "?")
        expected = set(rec.get("expected_capture_ids", []))
        threshold = float(
            rec.get("abstention_score_threshold", DEFAULT_ABSTENTION_THRESHOLD)
        )
        results = searcher.search(rec["query"], limit=k)
        retrieved = {h.capture_id for h in results}

        if axis == "abstention":
            # System should NOT confidently surface anything: a case is "hit"
            # when no result clears the confidence threshold.
            confident = [h for h in results if h.rrf_score >= threshold]
            success = len(confident) == 0
        else:
            success = bool(expected & retrieved)

        total += 1
        axis_totals[axis] += 1
        if success:
            hits += 1
            axis_hits[axis] += 1
        else:
            misses.append(rec["query"])

    by_axis = {
        ax: round(axis_hits[ax] / axis_totals[ax], 3) if axis_totals[ax] else 0.0
        for ax in axis_totals
    }
    return LongMemEvalResult(
        n=total,
        overall_accuracy=round(hits / total, 3) if total else 0.0,
        by_axis=by_axis,
        misses=misses,
    )
