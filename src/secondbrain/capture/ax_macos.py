"""macOS Accessibility-tree walk — gate 2 of the dedup cascade.

Walks the focused app's AX tree depth-first (capped at `MAX_NODES`) and hashes
the concatenated text. An unchanged hash lets the cascade skip the frame
without reading pixels.

Electron/Chromium hosts need `AXEnhancedUserInterface=true` before they expose
a tree; Metal-rendered surfaces never do, and fall through to dHash.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field

# On other platforms every entry point degrades to "AX unavailable".
_IS_MACOS = sys.platform == "darwin"

if _IS_MACOS:
    from ApplicationServices import (  # type: ignore[import-not-found]
        AXUIElementCopyAttributeNames,
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
        AXUIElementSetAttributeValue,
        kAXErrorSuccess,
    )
    from Cocoa import NSWorkspace  # type: ignore[import-not-found]


MAX_NODES = 1500
TEXT_ATTRS = ("AXValue", "AXTitle", "AXDescription", "AXHelp")


@dataclass
class AXSnapshot:
    app_name: str | None
    bundle_id: str | None
    pid: int | None
    text: str
    node_count: int
    truncated: bool
    # None whenever there is no AX signal (empty Electron trees, error paths).
    # The cascade's `ax_unchanged` gate falls through to pixel-based gates then.
    digest: bytes | None
    enhanced_toggled: bool = False
    error: str | None = None
    window_title: str | None = None
    extras: dict = field(default_factory=dict)


def _copy(elem: object, attr: str) -> object | None:
    if not _IS_MACOS:
        return None
    err, val = AXUIElementCopyAttributeValue(elem, attr, None)
    if err != kAXErrorSuccess:
        return None
    return val


def _attr_names(elem: object) -> list[str]:
    if not _IS_MACOS:
        return []
    err, names = AXUIElementCopyAttributeNames(elem, None)
    if err != kAXErrorSuccess or not names:
        return []
    return list(names)


def _maybe_enable_enhanced(app_elem: object) -> bool:
    """Ask Electron / Chromium hosts to expose their AX subtree."""
    if not _IS_MACOS:
        return False
    try:
        AXUIElementSetAttributeValue(app_elem, "AXEnhancedUserInterface", True)
        return True
    except Exception:
        return False


def _walk(
    elem: object,
    parts: list[str],
    counter: list[int],
    max_nodes: int,
) -> None:
    if counter[0] >= max_nodes:
        return
    counter[0] += 1
    for attr in TEXT_ATTRS:
        val = _copy(elem, attr)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    children = _copy(elem, "AXChildren") or []
    for child in children:
        if counter[0] >= max_nodes:
            return
        _walk(child, parts, counter, max_nodes)


def snapshot_focused_app(*, max_nodes: int = MAX_NODES) -> AXSnapshot:
    """Snapshot the AX subtree of the currently focused application.

    Returns an `AXSnapshot` whose `digest` is the SHA-256 of the concatenated
    text. Equal digests across consecutive frames → safe to skip.
    """
    if not _IS_MACOS:
        return AXSnapshot(
            app_name=None,
            bundle_id=None,
            pid=None,
            text="",
            node_count=0,
            truncated=False,
            digest=None,
            error="ax_macos: not running on macOS",
        )

    workspace = NSWorkspace.sharedWorkspace()
    front = workspace.frontmostApplication()
    if front is None:
        return AXSnapshot(
            app_name=None,
            bundle_id=None,
            pid=None,
            text="",
            node_count=0,
            truncated=False,
            digest=None,
            error="no frontmost app",
        )

    pid = int(front.processIdentifier())
    bundle_id = front.bundleIdentifier()
    app_name = front.localizedName()

    # The OS reports `loginwindow` as frontmost when this process lacks
    # Accessibility (TCC) permission — expected from a plain shell invocation.
    if bundle_id == "com.apple.loginwindow":
        return AXSnapshot(
            app_name=app_name,
            bundle_id=bundle_id,
            pid=pid,
            text="",
            node_count=0,
            truncated=False,
            digest=None,
            error=(
                "ax: frontmost reports as loginwindow — this process is missing "
                "Accessibility (TCC) permission. Grant it in System Settings → "
                "Privacy & Security → Accessibility. Until then, app_name + "
                "ax_text will be empty for every capture."
            ),
        )

    app_elem = AXUIElementCreateApplication(pid)
    enhanced_toggled = _maybe_enable_enhanced(app_elem)

    parts: list[str] = []
    counter = [0]
    try:
        focused = _copy(app_elem, "AXFocusedWindow") or app_elem
        _walk(focused, parts, counter, max_nodes)
    except Exception as e:
        return AXSnapshot(
            app_name=app_name,
            bundle_id=bundle_id,
            pid=pid,
            text="",
            node_count=counter[0],
            truncated=False,
            digest=None,
            enhanced_toggled=enhanced_toggled,
            error=f"walk_failed: {e!r}",
        )

    text = "\n".join(parts)
    # Never fabricate a digest for empty text: every frame would then look
    # "AX-unchanged" forever. None lets pixel hashes decide instead.
    digest = hashlib.sha256(text.encode("utf-8")).digest() if text else None

    window_title: str | None = None
    try:
        focused_window = _copy(app_elem, "AXFocusedWindow")
        if focused_window is not None:
            t = _copy(focused_window, "AXTitle")
            if isinstance(t, str):
                window_title = t
    except Exception:
        pass

    return AXSnapshot(
        app_name=app_name,
        bundle_id=bundle_id,
        pid=pid,
        text=text,
        node_count=counter[0],
        truncated=counter[0] >= max_nodes,
        digest=digest,
        enhanced_toggled=enhanced_toggled,
        window_title=window_title,
    )
