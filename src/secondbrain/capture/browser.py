"""Browser capture.

Three ingestion paths:
  - SingleFile-MV3 native-messaging host writes a self-contained .html into a
    watched folder; we ingest it as a `Capture(source='browser')`.
  - CDP fallback: open `chrome --remote-debugging-port` and call
    `Page.captureSnapshot` + `Accessibility.getFullAXTree`.
  - History importer: read Chrome/Firefox/Arc/Zen sqlite (IMMUTABLE+WAL copy)
    and emit one Capture per recently-visited URL.

This file ships the importer (the only path that needs no extension/CDP) and
the protocol surface for the other two.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from secondbrain.models import Capture

# Standard locations for browser history sqlite DBs on macOS.
HISTORY_PATHS = {
    "chrome": "~/Library/Application Support/Google/Chrome/Default/History",
    "arc": "~/Library/Application Support/Arc/User Data/Default/History",
    "edge": "~/Library/Application Support/Microsoft Edge/Default/History",
    # Firefox uses places.sqlite under each profile; resolved by `firefox_profile_path`.
}


def chromium_history(
    db_path: Path,
    *,
    since: datetime | None = None,
    limit: int = 500,
) -> Iterator[Capture]:
    """Yield browser-history Captures from a Chromium-family sqlite.

    We always copy the DB into a temp dir before opening so we don't fight
    the live browser for locks. Chromium stores `last_visit_time` as
    microseconds since 1601-01-01 UTC.
    """
    if not db_path.exists():
        return iter([])
    tmp = Path(tempfile.mkdtemp(prefix="sb_hist_"))
    try:
        cp = tmp / "History"
        shutil.copy2(db_path, cp)
        conn = sqlite3.connect(f"file:{cp}?immutable=1", uri=True)
        params: tuple = (limit,)
        where = ""
        if since is not None:
            chromium_epoch = (since - datetime(1601, 1, 1, tzinfo=UTC)).total_seconds() * 1_000_000
            where = "WHERE u.last_visit_time >= ?"
            params = (int(chromium_epoch), limit)
        rows = conn.execute(
            f"SELECT u.url, u.title, u.last_visit_time "
            f"FROM urls u {where} "
            f"ORDER BY u.last_visit_time DESC LIMIT ?",
            params,
        )
        for url, title, last_visit in rows:
            ts = datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=int(last_visit))
            yield Capture(
                id=f"browser:{abs(hash((url, last_visit))):016x}",
                source="browser",
                captured_at=ts,
                app_name="Chromium",
                window_title=title,
                url=url,
                ax_text=title,
            )
        conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def expand_history_paths() -> dict[str, Path]:
    return {k: Path(v).expanduser() for k, v in HISTORY_PATHS.items()}
