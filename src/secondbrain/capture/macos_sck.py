"""macOS ScreenCaptureKit frame source.

Spawns the bundled `secondbrain-capture` Swift sidecar (built via
`swift/SecondBrainCapture/`), reads NDJSON from its stdout, and yields
`Frame` objects.

Reconnect on crash: the source restarts the subprocess up to
`max_restarts` times before propagating the failure. Bounded backoff.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import shutil
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import structlog
from PIL import Image

from secondbrain.capture.frame import Frame

log = structlog.get_logger()


def _default_sidecar_path() -> Path:
    """Find the built sidecar binary.

    Resolution order:
      1. `$SECONDBRAIN_CAPTURE_BIN` env var (escape hatch).
      2. The release build under `swift/SecondBrainCapture/.build/release/`.
      3. Anything named `secondbrain-capture` on `PATH`.
    """
    if env := os.environ.get("SECONDBRAIN_CAPTURE_BIN"):
        return Path(env)

    repo_root = Path(__file__).resolve().parents[3]
    candidate = (
        repo_root / "swift" / "SecondBrainCapture" / ".build" / "release" / "secondbrain-capture"
    )
    if candidate.exists():
        return candidate

    on_path = shutil.which("secondbrain-capture")
    if on_path:
        return Path(on_path)

    raise FileNotFoundError(
        "secondbrain-capture binary not found. "
        "Build it with: cd swift/SecondBrainCapture && swift build -c release"
    )


class MacOSScreenSource:
    """SCK-backed FrameSource. macOS only.

    `pixel_mode`:
      - "png"  — sidecar emits inline base64 PNGs (good for tests / small fps).
      - "heic" — sidecar writes HEIC to `frame_dir`, NDJSON contains the path.
    """

    def __init__(
        self,
        *,
        pixel_mode: str = "png",
        frame_dir: Path | None = None,
        fps: int = 1,
        display_index: int = 0,
        max_frames: int = -1,
        max_restarts: int = 3,
        sidecar_path: Path | None = None,
    ) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("MacOSScreenSource requires macOS")
        if pixel_mode not in ("png", "heic"):
            raise ValueError("pixel_mode must be 'png' or 'heic'")
        if pixel_mode == "heic" and frame_dir is None:
            raise ValueError("pixel_mode='heic' requires frame_dir")
        self.pixel_mode = pixel_mode
        self.frame_dir = frame_dir
        self.fps = fps
        self.display_index = display_index
        self.max_frames = max_frames
        self.max_restarts = max_restarts
        self.sidecar = sidecar_path or _default_sidecar_path()
        self._proc: asyncio.subprocess.Process | None = None
        self._closed = False
        self._last_error: str | None = None

    def _build_args(self) -> list[str]:
        args = [
            str(self.sidecar),
            "--display",
            str(self.display_index),
            "--fps",
            str(self.fps),
        ]
        if self.pixel_mode == "png":
            args.append("--emit-png")
        else:
            assert self.frame_dir is not None
            args += ["--hevc-dir", str(self.frame_dir)]
        if self.max_frames > 0:
            args += ["--max-frames", str(self.max_frames)]
        return args

    # 64 MiB per NDJSON line — full-screen retina inline-PNG can be ~10 MiB.
    _STDOUT_LIMIT = 64 * 1024 * 1024

    async def _spawn(self) -> asyncio.subprocess.Process:
        log.info("sck.spawn", binary=str(self.sidecar))
        return await asyncio.create_subprocess_exec(
            *self._build_args(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=self._STDOUT_LIMIT,
        )

    async def stream(self) -> AsyncIterator[Frame]:
        restarts = 0
        while not self._closed:
            try:
                self._proc = await self._spawn()
                assert self._proc.stdout is not None
                async for frame in self._read_ndjson(self._proc.stdout):
                    yield frame
                # process exited cleanly
                rc = await self._proc.wait()
                if rc == 0 or self._closed:
                    return
                # Exit codes 2/3/4/5 from main.swift are hard setup failures
                # (no displays, perm denied, vision setup) — retrying won't
                # help. Fail fast with the actual error the user needs to see.
                if rc in (2, 3, 4, 5):
                    raise RuntimeError(
                        f"secondbrain-capture exited {rc}: "
                        f"{self._last_error or 'unknown'} — "
                        "this is usually a Screen Recording (TCC) permission "
                        "issue. Open System Settings → Privacy & Security → "
                        "Screen Recording and toggle `secondbrain-capture` on. "
                        "If that doesn't help, also enable it under Accessibility."
                    )
                log.warning("sck.exit_nonzero", rc=rc)
            except RuntimeError:
                raise
            except Exception as e:
                log.warning("sck.error", err=repr(e))
            restarts += 1
            if restarts > self.max_restarts:
                raise RuntimeError(
                    f"secondbrain-capture failed after {self.max_restarts} "
                    f"restarts. Last sidecar message: "
                    f"{self._last_error or '(none)'}"
                )
            await asyncio.sleep(min(2**restarts, 10))

    async def _read_ndjson(self, stdout: asyncio.StreamReader) -> AsyncIterator[Frame]:
        while True:
            line = await stdout.readline()
            if not line:
                return
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                log.warning("sck.bad_json", raw=line[:200].decode("utf-8", "ignore"))
                continue
            etype = event.get("type")
            if etype == "ready":
                log.info("sck.ready", displays=event.get("displays"))
                continue
            if etype == "error":
                msg = event.get("msg", "")
                self._last_error = msg
                log.warning("sck.error_event", msg=msg)
                continue
            if etype == "frame":
                frame = self._parse_frame(event)
                if frame is not None:
                    yield frame

    def _parse_frame(self, event: dict) -> Frame | None:
        try:
            ts = float(event["ts"])
            captured_at = datetime.fromtimestamp(ts, tz=UTC)
        except (KeyError, ValueError):
            return None

        image: Image.Image | None = None
        if "png_b64" in event:
            try:
                raw = base64.b64decode(event["png_b64"])
                image = Image.open(io.BytesIO(raw)).convert("RGB")
            except Exception as e:
                log.warning("sck.png_decode_failed", err=repr(e))
                return None
        elif "frame_path" in event:
            try:
                image = Image.open(event["frame_path"]).convert("RGB")
            except Exception as e:
                log.warning(
                    "sck.heic_open_failed",
                    path=event.get("frame_path"),
                    err=repr(e),
                )
                return None

        if image is None:
            return None

        # Snapshot the focused app's AX subtree at frame time. This is the
        # single thing that turns "anonymous pixels" into "this is Slack
        # showing a message from Sam about Snowflake." Without it, no
        # downstream feature works: deny-list, capability cache, person
        # extraction, search by app, broken-promise detection — all need
        # `app_name` + `ax_text`.
        ax_app = ax_bundle = ax_window = ax_text = None
        ax_digest = None
        try:
            from secondbrain.capture.ax_macos import snapshot_focused_app

            snap = snapshot_focused_app()
            if snap.error is None:
                ax_app = snap.app_name
                ax_bundle = snap.bundle_id
                ax_window = snap.window_title
                ax_text = snap.text or None
                ax_digest = snap.digest
            else:
                # The most common error is "missing Accessibility permission"
                # — surface it loudly to the user the first time it happens
                # so they don't silently capture anonymous pixels for hours.
                log.warning("sck.ax_unavailable", err=snap.error)
        except Exception as e:
            log.debug("sck.ax_snapshot_failed", err=repr(e))

        return Frame(
            captured_at=captured_at,
            image=image,
            monitor_index=int(event.get("monitor_index", 0)),
            app_name=ax_app,
            app_bundle_id=ax_bundle,
            window_title=ax_window,
            ax_text=ax_text,
            ax_text_digest=ax_digest,
            dirty_rect_fraction=(
                float(event["dirty_rect_fraction"])
                if event.get("dirty_rect_fraction") is not None
                and event["dirty_rect_fraction"] >= 0
                else None
            ),
            extras={"frame_path": event.get("frame_path")},
        )

    async def close(self) -> None:
        self._closed = True
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except (TimeoutError, ProcessLookupError):
                with contextlib_suppress(ProcessLookupError):
                    self._proc.kill()


# Inline contextlib.suppress to avoid an extra import.
class contextlib_suppress:
    def __init__(self, *exc):
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        return et is not None and issubclass(et, self.exc)
