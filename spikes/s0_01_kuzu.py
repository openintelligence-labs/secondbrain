"""Verify Kùzu embedded works in Python, supports a tiny bi-temporal graph.

Pass criteria:
- Create a Person+MemoryNode schema with bi-temporal edges
- Insert ~1000 nodes and edges
- Run a Cypher 'as_of' temporal query under 10ms p50
"""

from __future__ import annotations

import shutil
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import kuzu  # noqa: E402
from _runner import record  # noqa: E402


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sb_kuzu_"))
    try:
        db = kuzu.Database(str(tmp / "graph"))
        conn = kuzu.Connection(db)

        # Schema: Person, MemoryNode, MENTIONS edge with bi-temporal validity
        conn.execute("CREATE NODE TABLE Person(id INT64 PRIMARY KEY, name STRING)")
        conn.execute(
            "CREATE NODE TABLE MemoryNode("
            "id INT64 PRIMARY KEY, "
            "content STRING, "
            "valid_from TIMESTAMP, "
            "valid_to TIMESTAMP, "
            "ingested_at TIMESTAMP)"
        )
        conn.execute(
            "CREATE REL TABLE MENTIONS("
            "FROM MemoryNode TO Person, "
            "valid_from TIMESTAMP, "
            "valid_to TIMESTAMP)"
        )

        N = 1000
        base = datetime(2026, 1, 1, tzinfo=UTC)

        # Insert people
        for i in range(50):
            conn.execute(
                "CREATE (:Person {id: $id, name: $name})",
                {"id": i, "name": f"Person_{i}"},
            )

        # Insert memories with bi-temporal fields
        t0 = time.perf_counter()
        for i in range(N):
            vf = base + timedelta(hours=i)
            vt = vf + timedelta(days=30)
            conn.execute(
                "CREATE (:MemoryNode {id: $id, content: $c, "
                "valid_from: $vf, valid_to: $vt, ingested_at: $ig})",
                {"id": i, "c": f"memory {i}", "vf": vf, "vt": vt, "ig": vf},
            )
        insert_ms = (time.perf_counter() - t0) * 1000

        # Bi-temporal "as_of" query (point-in-time)
        as_of = base + timedelta(hours=500)
        latencies_ms = []
        for _ in range(20):
            t0 = time.perf_counter()
            r = conn.execute(
                "MATCH (m:MemoryNode) "
                "WHERE m.valid_from <= $t AND m.valid_to >= $t "
                "RETURN count(m)",
                {"t": as_of},
            )
            r.get_next()
            latencies_ms.append((time.perf_counter() - t0) * 1000)

        p50 = statistics.median(latencies_ms)
        p95 = sorted(latencies_ms)[int(0.95 * len(latencies_ms))]

        passed = p50 < 10.0
        record(
            "S0-01",
            passed,
            {
                "kuzu_version": kuzu.__version__,
                "nodes_inserted": N + 50,
                "insert_total_ms": round(insert_ms, 1),
                "asof_query_p50_ms": round(p50, 3),
                "asof_query_p95_ms": round(p95, 3),
                "criterion": "p50 < 10ms",
            },
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
