"""Pre-flight checks for `secondbrain ui` and `secondbrain run`.

Each check returns a `Check` with a status and an actionable hint:

  sck.sidecar        — Swift binary present + executable
  sck.tcc            — Screen Recording permission granted (probed)
  ollama.reachable   — `ollama serve` answering on localhost
  ollama.model       — at least one LLM model pulled
  embedder.model     — sentence-transformers Nomic v2 weights cached
  keychain.access    — keyring read/write round-trip
  disk.free          — > 1 GiB free under ~/.secondbrain
  stores.writable    — each store dir is creatable + writable
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Status = Literal["ok", "warn", "fail", "skip"]


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str
    fix: str | None = None

    def __str__(self) -> str:  # for CLI rendering
        glyph = {"ok": "✓", "warn": "~", "fail": "✗", "skip": "·"}[self.status]
        line = f"  {glyph} {self.name:<22} {self.detail}"
        if self.fix and self.status in {"fail", "warn"}:
            line += f"\n    → fix: {self.fix}"
        return line


def _check_sck_sidecar() -> Check:
    if os.uname().sysname != "Darwin":
        return Check("sck.sidecar", "skip", "non-macOS host")
    try:
        from secondbrain.capture.macos_sck import _default_sidecar_path

        path = _default_sidecar_path()
        if not os.access(path, os.X_OK):
            return Check(
                "sck.sidecar",
                "fail",
                f"{path} exists but not executable",
                fix=f"chmod +x {path}",
            )
        return Check("sck.sidecar", "ok", str(path))
    except FileNotFoundError as e:
        return Check(
            "sck.sidecar",
            "fail",
            str(e),
            fix="cd swift/SecondBrainCapture && swift build -c release",
        )


def _check_sck_tcc(timeout_s: float = 4.0) -> Check:
    """Spawn the sidecar with max_frames=1 and see if it actually returns a
    frame. If macOS hasn't granted Screen Recording yet, SCK silently emits
    black frames or fails to start — either way we won't get a real frame
    within the timeout."""
    if os.uname().sysname != "Darwin":
        return Check("sck.tcc", "skip", "non-macOS host")
    try:
        from secondbrain.capture.macos_sck import _default_sidecar_path

        sidecar = _default_sidecar_path()
    except FileNotFoundError:
        return Check("sck.tcc", "skip", "sidecar not built — see sck.sidecar")

    try:
        proc = subprocess.Popen(
            [str(sidecar), "--fps", "1", "--max-frames", "1", "--emit-png"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, _stderr = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate(timeout=1.0)
        if not stdout:
            return Check(
                "sck.tcc",
                "fail",
                "no NDJSON emitted within timeout",
                fix=(
                    "System Settings → Privacy & Security → Screen Recording "
                    "→ enable Terminal (or your runner)"
                ),
            )
        # Sidecar emits NDJSON. First line is usually a "ready" header,
        # subsequent lines are frames. Scan for the first frame-shaped record.
        saw_ready = False
        for line in stdout.splitlines():
            try:
                data = json.loads(line)
            except Exception:
                continue
            t = data.get("type")
            if t == "ready":
                saw_ready = True
                continue
            if t == "error":
                return Check(
                    "sck.tcc",
                    "fail",
                    f"sidecar error: {data.get('msg', '?')}",
                    fix=(
                        "rebuild the sidecar with: "
                        "cd swift/SecondBrainCapture && swift build -c release"
                    ),
                )
            if "image_b64" in data or "image_path" in data or "png" in data:
                return Check("sck.tcc", "ok", "captured 1 frame")
        # NDJSON but no frame — typically TCC denied.
        if saw_ready:
            return Check(
                "sck.tcc",
                "fail",
                "sidecar started but emitted no frames (TCC likely denied)",
                fix="System Settings → Privacy & Security → Screen Recording → enable Terminal",
            )
        return Check(
            "sck.tcc",
            "fail",
            "sidecar emitted only non-frame messages",
            fix="rebuild the sidecar; check version matches Python client",
        )
    except Exception as e:
        return Check(
            "sck.tcc", "fail", repr(e), fix="rerun with SECONDBRAIN_DEBUG=1 to see sidecar stderr"
        )


def _check_ollama_reachable() -> Check:
    base = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    if not base.startswith("http"):
        base = f"http://{base}"
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=1.5) as r:
            body = json.loads(r.read())
            models = body.get("models", [])
            return Check(
                "ollama.reachable",
                "ok",
                f"{base} · {len(models)} model(s)",
            )
    except urllib.error.URLError as e:
        return Check(
            "ollama.reachable",
            "fail",
            f"{base} unreachable ({e.reason})",
            fix="brew install ollama && ollama serve  (or set OLLAMA_HOST)",
        )
    except Exception as e:
        return Check("ollama.reachable", "fail", repr(e), fix="brew install ollama && ollama serve")


def _check_ollama_model(want_model: str | None = None) -> Check:
    base = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    if not base.startswith("http"):
        base = f"http://{base}"
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=1.5) as r:
            body = json.loads(r.read())
            models = [m["name"] for m in body.get("models", [])]
    except Exception:
        return Check("ollama.model", "skip", "ollama not reachable")

    if not models:
        return Check(
            "ollama.model",
            "fail",
            "no models pulled",
            fix="ollama pull llama3.1  (or any model you prefer)",
        )
    if want_model and not any(want_model in m for m in models):
        return Check(
            "ollama.model",
            "warn",
            f"want={want_model} not pulled; available={', '.join(models[:4])}",
            fix=f"ollama pull {want_model}",
        )
    return Check("ollama.model", "ok", f"models: {', '.join(models[:4])}")


def _check_embedder_model() -> Check:
    """Nomic v2 lives under ~/.cache/huggingface/hub/ once sentence-transformers
    has downloaded it. We don't import the model (too slow) — we just check
    for the cached snapshot."""
    cache = Path.home() / ".cache" / "huggingface" / "hub"
    if not cache.exists():
        return Check(
            "embedder.model",
            "warn",
            "HF cache empty — first launch will download Nomic v2 (~500MB)",
            fix="run a small `secondbrain index` once to seed the cache",
        )
    # Heuristic: any nomic-* snapshot is good enough.
    nomic = list(cache.glob("models--nomic-ai--*"))
    if not nomic:
        return Check(
            "embedder.model",
            "warn",
            f"HF cache present but no Nomic snapshot ({len(list(cache.iterdir()))} other models)",
            fix="first `secondbrain ui` launch will trigger the download",
        )
    return Check("embedder.model", "ok", f"{nomic[0].name}")


def _check_keychain() -> Check:
    if os.uname().sysname != "Darwin":
        # `keyring` falls back to a keyring file or DBus on other platforms.
        return Check("keychain.access", "skip", "non-macOS host")
    try:
        import keyring

        probe_service = "secondbrain.preflight.probe"
        probe_value = os.urandom(8).hex()
        keyring.set_password(probe_service, "preflight", probe_value)
        got = keyring.get_password(probe_service, "preflight")
        keyring.delete_password(probe_service, "preflight")
        if got != probe_value:
            return Check(
                "keychain.access",
                "fail",
                "round-trip mismatch",
                fix="check Keychain Access permissions",
            )
        return Check("keychain.access", "ok", "round-trip succeeded")
    except Exception as e:
        return Check(
            "keychain.access",
            "fail",
            repr(e),
            fix="unlock the login keychain in Keychain Access.app",
        )


def _check_disk_free(db_path: Path) -> Check:
    try:
        st = shutil.disk_usage(
            str(db_path.parent if db_path.parent.exists() else db_path.parent.parent)
        )
        free_gib = st.free / (1024**3)
        if free_gib < 1.0:
            return Check(
                "disk.free",
                "fail",
                f"{free_gib:.2f} GiB free",
                fix="free space under your home directory",
            )
        if free_gib < 5.0:
            return Check("disk.free", "warn", f"{free_gib:.2f} GiB free")
        return Check("disk.free", "ok", f"{free_gib:.1f} GiB free")
    except Exception as e:
        return Check("disk.free", "warn", repr(e))


def _check_stores_writable(db_path: Path) -> Check:
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        for sub in ("lance", "tantivy", "kg", "logs"):
            (db_path.parent / sub).mkdir(parents=True, exist_ok=True)
        probe = db_path.parent / ".preflight"
        probe.write_text("ok")
        probe.unlink()
        return Check("stores.writable", "ok", str(db_path.parent))
    except Exception as e:
        return Check(
            "stores.writable", "fail", repr(e), fix=f"chmod the directory: {db_path.parent}"
        )


def run_preflight(db_path: Path, *, probe_tcc: bool = True) -> list[Check]:
    """Run every check. Order matters: cheap things first, slow probes last."""
    checks: list[Check] = []
    checks.append(_check_disk_free(db_path))
    checks.append(_check_stores_writable(db_path))
    checks.append(_check_keychain())
    checks.append(_check_sck_sidecar())
    if probe_tcc:
        checks.append(_check_sck_tcc())
    checks.append(_check_ollama_reachable())
    checks.append(_check_ollama_model())
    checks.append(_check_embedder_model())
    return checks


def gate(checks: list[Check]) -> tuple[bool, list[Check]]:
    """Decide whether launch may proceed. Returns (ok, blockers).

    Policy: any `fail` in a load-bearing check blocks. `embedder.model`
    failing is *not* a blocker — first launch downloads on demand. Same
    for `ollama.*` warnings — heuristic fallbacks cover them.
    """
    blockers = [
        c
        for c in checks
        if c.status == "fail"
        and c.name not in {"embedder.model", "ollama.model", "ollama.reachable"}
    ]
    return (len(blockers) == 0, blockers)
