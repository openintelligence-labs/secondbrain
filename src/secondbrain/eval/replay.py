"""Replay eval harness.

Reads a JSONL file of `(query, expected_capture_ids)` pairs and reports
recall@K plus latency p50/p95. The baseline; LongMemEval and LoCoMo will
graft onto the same surface.

JSONL schema:
    {"query": "...", "expected": ["capture_id_1", "capture_id_2"]}
"""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from secondbrain.search.hybrid import HybridSearcher


@dataclass
class ReplayCase:
    query: str
    expected: set[str]


@dataclass
class ReplayResult:
    n: int
    recall_at_k: float
    p50_ms: float
    p95_ms: float
    misses: list[str]


def load_cases(path: Path) -> list[ReplayCase]:
    out: list[ReplayCase] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        out.append(ReplayCase(query=rec["query"], expected=set(rec["expected"])))
    return out


def run(
    searcher: HybridSearcher,
    cases: list[ReplayCase],
    *,
    k: int = 10,
) -> ReplayResult:
    hits = 0
    timings: list[float] = []
    misses: list[str] = []
    for case in cases:
        t0 = time.perf_counter()
        results = searcher.search(case.query, limit=k)
        timings.append((time.perf_counter() - t0) * 1000)
        retrieved = {h.capture_id for h in results}
        if case.expected & retrieved:
            hits += 1
        else:
            misses.append(case.query)
    if not cases:
        return ReplayResult(0, 0.0, 0.0, 0.0, [])
    timings_sorted = sorted(timings)
    p50 = statistics.median(timings_sorted)
    p95 = timings_sorted[int(0.95 * len(timings_sorted))] if len(timings_sorted) > 1 else timings_sorted[0]
    return ReplayResult(
        n=len(cases),
        recall_at_k=hits / len(cases),
        p50_ms=round(p50, 2),
        p95_ms=round(p95, 2),
        misses=misses,
    )
