"""FadeMem dual half-life decay.

Importance-gated: high-importance memories decay slowly (~11.25d half-life),
low-importance fast (~5.02d). Follows the ACT-R / FadeMem activation model.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

LONG_HALF_LIFE_DAYS = 11.25
SHORT_HALF_LIFE_DAYS = 5.02
IMPORTANCE_PIVOT = 5.0  # importance >= pivot uses long half-life


def half_life_days(importance: float) -> float:
    return LONG_HALF_LIFE_DAYS if importance >= IMPORTANCE_PIVOT else SHORT_HALF_LIFE_DAYS


def decay_factor(*, ingested_at: datetime, importance: float, now: datetime | None = None) -> float:
    """Return current strength in [0, 1]."""
    now = now or datetime.now(UTC)
    if ingested_at.tzinfo is None:
        ingested_at = ingested_at.replace(tzinfo=UTC)
    age_days = max((now - ingested_at).total_seconds() / 86400.0, 0.0)
    h = half_life_days(importance)
    return math.pow(0.5, age_days / h)
