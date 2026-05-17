"""Optional biometric (Touch ID / Apple Watch) gate for destructive ops.

When `SECONDBRAIN_REQUIRE_BIOMETRIC=1` is set, the MCP `memory.forget` and
HTTP `/forget` endpoints invoke the `secondbrain-auth` Swift helper before
any cascading delete. The helper opens an `LAContext` and blocks until the
user authenticates.

Off by default. Opt-in via env var. Always succeeds (no-op) on non-macOS or
when the helper binary is unbuilt — that's the v1 escape hatch; v1.1 may
make it a hard requirement when configured.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _auth_binary() -> Path | None:
    repo_root = Path(__file__).resolve().parents[3]
    candidate = (
        repo_root / "swift" / "SecondBrainCapture" / ".build" / "release" / "secondbrain-auth"
    )
    if candidate.exists():
        return candidate
    on_path = shutil.which("secondbrain-auth")
    return Path(on_path) if on_path else None


def is_required() -> bool:
    return os.environ.get("SECONDBRAIN_REQUIRE_BIOMETRIC", "") == "1"


class BiometricDenied(RuntimeError):
    """Raised when the operator explicitly opted into biometric gating and
    auth was denied / unavailable."""


def confirm(reason: str) -> bool:
    """Return True if biometric auth succeeds, the gate is disabled, or the
    platform doesn't support it. Raises `BiometricDenied` only when auth was
    required, attempted, and refused.
    """
    if not is_required():
        return True
    if sys.platform != "darwin":
        return True  # LocalAuthentication is macOS-only
    binary = _auth_binary()
    if binary is None:
        # Operator turned on biometrics but didn't build the helper.
        # Fail closed: this is the paranoid path; refuse rather than
        # silently letting the delete through.
        raise BiometricDenied(
            "SECONDBRAIN_REQUIRE_BIOMETRIC=1 but secondbrain-auth not built. "
            "Build it with: cd swift/SecondBrainCapture && swift build -c release"
        )
    proc = subprocess.run(
        [str(binary), reason],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode == 0:
        return True
    raise BiometricDenied(f"biometric auth refused (rc={proc.returncode}): {proc.stderr.strip()}")
