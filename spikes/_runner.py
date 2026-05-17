"""Tiny spike result helper. Each spike imports `record(...)` and calls it once."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

RESULTS_PATH = Path(__file__).parent / "results.json"


def record(spike_id: str, passed: bool, details: dict[str, Any]) -> None:
    """Append/overwrite this spike's result in results.json."""
    data: dict[str, Any] = {}
    if RESULTS_PATH.exists():
        data = json.loads(RESULTS_PATH.read_text())
    data[spike_id] = {
        "passed": passed,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **details,
    }
    RESULTS_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    status = "PASS" if passed else "FAIL"
    print(f"\n{spike_id}: {status}")
    for k, v in details.items():
        print(f"  {k}: {v}")
    sys.exit(0 if passed else 1)
