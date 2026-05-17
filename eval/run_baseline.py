"""Reproducible eval baseline runner.

Loads `eval/corpus.json` (13 captures) + `eval/longmemeval_synthetic.jsonl`
(30 queries across 5 LongMemEval-shaped axes), indexes the corpus into a
fresh LanceDB + tantivy + Kùzu, then runs the harness against the KG-aware
searcher.

Run:
    .venv/bin/python eval/run_baseline.py --embedder stub
    .venv/bin/python eval/run_baseline.py --embedder nomic
    .venv/bin/python eval/run_baseline.py --embedder nomic --rerank
    .venv/bin/python eval/run_baseline.py --matrix    # all 4 cells

Outputs:
    eval/baseline_results.json  (single run)
    eval/baseline_matrix.json   (matrix run)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "src"))


def _build(embedder_kind: str, *, slot: str):
    from secondbrain.embed.stub import StubEmbedder
    from secondbrain.embed.text import TextEmbedder
    from secondbrain.indexing import Indexer
    from secondbrain.memory.amem import AMemLinker
    from secondbrain.memory.entities import EntityResolver
    from secondbrain.memory.pipeline import MemoryPipeline
    from secondbrain.models import Capture
    from secondbrain.search.hybrid import HybridSearcher
    from secondbrain.search.kg_filter import KGAwareSearcher
    from secondbrain.store.kg import KnowledgeGraph
    from secondbrain.store.text_index import TextIndex
    from secondbrain.store.vector import VectorStore

    workdir = ROOT / f"_workdir_{slot}"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir()

    if embedder_kind == "stub":
        embedder = StubEmbedder()
        embedder_name = "stub-deterministic-768d"
    elif embedder_kind == "nomic":
        embedder = TextEmbedder()
        embedder_name = "nomic-embed-text-v2-moe"
    else:
        raise ValueError(f"unknown embedder: {embedder_kind}")

    vector = VectorStore(db_path=workdir / "lance")
    text = TextIndex(index_path=workdir / "tantivy")
    kg = KnowledgeGraph(db_path=workdir / "kg")
    indexer = Indexer(embedder=embedder, vector=vector, text=text)
    pipe = MemoryPipeline(
        kg=kg,
        linker=AMemLinker(embedder=embedder),
        resolver=EntityResolver(kg=kg),
    )

    corpus = json.loads((ROOT / "corpus.json").read_text())
    for cap_d in corpus["captures"]:
        ts = datetime.fromisoformat(cap_d["ts"].replace("Z", "+00:00"))
        cap = Capture(
            id=cap_d["id"],
            captured_at=ts,
            app_name=cap_d["app"],
            app_bundle_id=f"com.example.{cap_d['app'].lower()}",
            ax_text=cap_d["text"],
        )
        indexer.index_capture(cap)
        pipe.ingest(cap)

    inner = HybridSearcher(text_index=text, vector_store=vector, embedder=embedder)
    searcher = KGAwareSearcher(kg=kg, inner=inner)
    return searcher, embedder_name, len(corpus["captures"])


def _run(embedder_kind: str, *, rerank: bool, slot: str) -> dict:
    from secondbrain.eval.longmemeval import run as run_lme

    searcher, embedder_name, n_caps = _build(embedder_kind, slot=slot)

    # Optionally wrap with a reranker.
    if rerank:
        from secondbrain.search.rerank import Reranker

        rr = Reranker()

        class _RerankShim:
            """Mimics HybridSearcher.search but applies the reranker on top."""

            def __init__(self, base) -> None:
                self.base = base

            def search(self, query: str, *, limit: int = 10):
                hits = self.base.search(query, limit=max(limit, 30))
                if not hits:
                    return hits
                ranking = rr.rerank(query, [h.body for h in hits], top_k=limit)
                if not ranking or all(score == 0.0 for _, score in ranking):
                    return hits[:limit]
                return [hits[i] for i, _ in ranking]

        searcher = _RerankShim(searcher)

    cases = ROOT / "longmemeval_synthetic.jsonl"
    t0 = time.perf_counter()
    result = run_lme(searcher, cases, k=10)
    elapsed_s = time.perf_counter() - t0

    return {
        "embedder": embedder_name,
        "rerank": rerank,
        "n_captures": n_caps,
        "n_cases": result.n,
        "overall_accuracy": result.overall_accuracy,
        "by_axis_accuracy": result.by_axis,
        "misses": result.misses,
        "elapsed_seconds": round(elapsed_s, 2),
        "ts": datetime.now().isoformat(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedder", choices=["stub", "nomic"], default="stub")
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument(
        "--llm-scorer",
        action="store_true",
        help="Use actants LLM importance scorer during corpus ingestion",
    )
    ap.add_argument(
        "--llm-model",
        default=None,
        help="Override the actants LLM model (e.g. gpt-oss:20b-cloud)",
    )
    ap.add_argument(
        "--matrix", action="store_true", help="run all 4 cells: stub|nomic × rerank-off|on"
    )
    args = ap.parse_args()

    if args.llm_scorer:
        from secondbrain.memory.importance import use_actants_scorer

        use_actants_scorer(model=args.llm_model)

    if args.matrix:
        cells = []
        for emb in ("stub", "nomic"):
            for rr in (False, True):
                slot = f"{emb}_{'rr' if rr else 'norr'}"
                cell = _run(emb, rerank=rr, slot=slot)
                cells.append(cell)
                print(
                    json.dumps(
                        {
                            k: cell[k]
                            for k in (
                                "embedder",
                                "rerank",
                                "overall_accuracy",
                                "by_axis_accuracy",
                                "elapsed_seconds",
                            )
                        },
                        indent=2,
                    )
                )
        (ROOT / "baseline_matrix.json").write_text(json.dumps(cells, indent=2) + "\n")
        return

    out = _run(args.embedder, rerank=args.rerank, slot="single")
    out["llm_scorer"] = args.llm_scorer
    out["llm_model"] = args.llm_model
    (ROOT / "baseline_results.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
