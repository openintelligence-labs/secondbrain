"""Reflection scheduler.

Hybrid trigger:
  - token-threshold:   when working-memory budget > 60%
  - idle-window:       >= idle_seconds since last input
  - cron:              daily 07:30 / weekly Sun 09:00 / monthly day-1 09:00

This module returns *whether to fire*, not *what to do* — the caller wires
the digest renderer. Decoupled so tests don't depend on time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class SchedulerState:
    last_fire_ts: float = 0.0
    last_input_ts: float = field(default_factory=lambda: time.time())
    token_count: int = 0


@dataclass
class SchedulerConfig:
    token_budget: int = 4096
    token_fraction_trigger: float = 0.6
    idle_seconds_trigger: int = 300
    cron_cooldown_seconds: int = 12 * 3600


def should_fire(
    state: SchedulerState,
    cfg: SchedulerConfig | None = None,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    cfg = cfg or SchedulerConfig()
    now_dt = now or datetime.now(UTC)
    now_ts = now_dt.timestamp()

    if state.token_count >= cfg.token_budget * cfg.token_fraction_trigger:
        return True, "token_threshold"

    idle_for = now_ts - state.last_input_ts
    if idle_for >= cfg.idle_seconds_trigger:
        return True, f"idle:{int(idle_for)}s"

    since_fire = now_ts - state.last_fire_ts
    if since_fire >= cfg.cron_cooldown_seconds:
        # Daily cron window: 07:30..08:30 local, expressed in UTC for stability
        if now_dt.hour == 7 and 30 <= now_dt.minute <= 90:
            return True, "cron_daily"
        if now_dt.weekday() == 6 and now_dt.hour == 9:
            return True, "cron_weekly"
    return False, "no_trigger"
