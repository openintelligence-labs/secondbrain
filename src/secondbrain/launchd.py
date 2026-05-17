"""macOS LaunchAgent installer.

`secondbrain install-agent` writes a per-user plist at
~/Library/LaunchAgents/com.openintelligencelabs.secondbrain.plist and loads
it via `launchctl bootstrap gui/<uid>`. The plist supervises:

    secondbrain run --db <db> [--ui-gateway] [extra args from --extra]

Logs land in ~/.secondbrain/logs/.

`uninstall-agent` does the reverse: bootout + plist removal.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LABEL = "com.openintelligencelabs.secondbrain"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = Path.home() / ".secondbrain" / "logs"


@dataclass
class AgentSpec:
    secondbrain_bin: Path
    db_path: Path
    label: str = LABEL
    log_dir: Path = LOG_DIR
    extra_args: tuple[str, ...] = ()
    env_vars: tuple[tuple[str, str], ...] = ()


def render_plist(spec: AgentSpec) -> str:
    """Render the launchd plist as XML text. Used directly by tests."""
    extra_args_xml = "".join(f"        <string>{a}</string>\n" for a in spec.extra_args)
    env_xml = "".join(
        f"        <key>{k}</key>\n        <string>{v}</string>\n" for k, v in spec.env_vars
    )

    template_path = Path(__file__).parent / "templates" / "launchd.plist.tmpl"
    template = template_path.read_text()
    return template.format(
        label=spec.label,
        secondbrain_bin=spec.secondbrain_bin,
        db_path=spec.db_path,
        log_dir=spec.log_dir,
        extra_args=extra_args_xml.rstrip("\n"),
        env_vars=env_xml.rstrip("\n"),
    )


def write_plist(spec: AgentSpec, dest: Path = PLIST_PATH) -> Path:
    """Render and write the plist. Returns the path written."""
    body = render_plist(spec)
    # Validate as plist before writing — catches a malformed template early.
    plistlib.loads(body.encode("utf-8"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    spec.log_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(body)
    return dest


def install(spec: AgentSpec, *, dest: Path = PLIST_PATH) -> Path:
    """Write the plist and load it via launchctl. macOS-only."""
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent install only supported on macOS")
    path = write_plist(spec, dest=dest)
    uid = os.getuid()
    # If a previous version was loaded, unload it first (idempotent install).
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(path)],
        check=False,
        capture_output=True,
    )
    proc = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"launchctl bootstrap failed (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    return path


def uninstall(*, dest: Path = PLIST_PATH) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent install only supported on macOS")
    uid = os.getuid()
    if dest.exists():
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}", str(dest)],
            check=False,
            capture_output=True,
        )
        dest.unlink()


def status(*, dest: Path = PLIST_PATH) -> dict:
    """Inspect whether the agent is installed + running."""
    out: dict = {"plist_path": str(dest), "plist_present": dest.exists()}
    if sys.platform != "darwin":
        out["loaded"] = None
        return out
    uid = os.getuid()
    proc = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{LABEL}"],
        check=False,
        capture_output=True,
        text=True,
    )
    out["loaded"] = proc.returncode == 0
    out["launchctl_rc"] = proc.returncode
    return out


def resolve_secondbrain_bin() -> Path:
    """Find the `secondbrain` executable on PATH; fall back to sys.executable -m."""
    bin_str = shutil.which("secondbrain")
    if bin_str:
        return Path(bin_str)
    # Fallback: invoke via current python interpreter.
    return Path(sys.executable)
