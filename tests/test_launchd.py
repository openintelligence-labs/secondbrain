"""LaunchAgent plist rendering — verify the template is valid and substitutes
the operator-supplied values into a parseable plist."""

from __future__ import annotations

import plistlib
from pathlib import Path

from secondbrain.launchd import AgentSpec, render_plist, write_plist


def test_rendered_plist_parses_as_xml(tmp_path: Path) -> None:
    spec = AgentSpec(
        secondbrain_bin=Path("/usr/local/bin/secondbrain"),
        db_path=tmp_path / "sb.db",
        log_dir=tmp_path / "logs",
    )
    body = render_plist(spec)
    parsed = plistlib.loads(body.encode("utf-8"))
    assert parsed["Label"].startswith("com.openintelligencelabs.secondbrain")
    assert "/usr/local/bin/secondbrain" in parsed["ProgramArguments"]
    assert "run" in parsed["ProgramArguments"]
    assert parsed["KeepAlive"]["Crashed"] is True
    assert parsed["RunAtLoad"] is True


def test_extra_args_threaded_through(tmp_path: Path) -> None:
    spec = AgentSpec(
        secondbrain_bin=Path("/usr/bin/python"),
        db_path=tmp_path / "x.db",
        extra_args=("--stub-embedder", "--llm"),
    )
    parsed = plistlib.loads(render_plist(spec).encode("utf-8"))
    assert "--stub-embedder" in parsed["ProgramArguments"]
    assert "--llm" in parsed["ProgramArguments"]


def test_env_vars_emitted(tmp_path: Path) -> None:
    spec = AgentSpec(
        secondbrain_bin=Path("/usr/local/bin/secondbrain"),
        db_path=tmp_path / "x.db",
        env_vars=(("SECONDBRAIN_LLM_PROVIDER", "ollama"),),
    )
    parsed = plistlib.loads(render_plist(spec).encode("utf-8"))
    assert parsed["EnvironmentVariables"]["SECONDBRAIN_LLM_PROVIDER"] == "ollama"


def test_write_plist_to_disk(tmp_path: Path) -> None:
    spec = AgentSpec(
        secondbrain_bin=Path("/usr/local/bin/secondbrain"),
        db_path=tmp_path / "sb.db",
        log_dir=tmp_path / "logs",
    )
    dest = tmp_path / "plist" / "sb.plist"
    out = write_plist(spec, dest=dest)
    assert out.exists()
    plistlib.loads(out.read_bytes())  # should not raise
