"""--offline must engage the air-gap socket guard before any subcommand runs."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from secondbrain.cli import main
from secondbrain.compliance.air_gap import disengage, is_engaged


@pytest.fixture(autouse=True)
def _reset_airgap():
    yield
    disengage()


def test_offline_flag_engages_air_gap_for_subcommand():
    """We don't have a side-effect-free subcommand that dials out, so we
    invoke a no-op command (`status` on an absent DB) with --offline and
    verify the air-gap is engaged inside the click group callback. The
    subcommand also gets to read ctx.obj["offline"]."""
    runner = CliRunner()

    assert is_engaged() is False

    # Without --db, status() returns early, but the group callback has already
    # engaged the guard. CliRunner finalises ctx between invocations, so the
    # check has to run from inside a command that is still alive.
    seen: list[bool] = []

    @main.command(name="airgap-probe", hidden=True)
    def probe():
        seen.append(is_engaged())

    result = runner.invoke(main, ["--offline", "airgap-probe"])
    assert result.exit_code == 0, result.output
    assert seen == [True]


def test_no_offline_flag_leaves_socket_alone():
    runner = CliRunner()
    seen: list[bool] = []

    @main.command(name="airgap-probe-noflag", hidden=True)
    def probe():
        seen.append(is_engaged())

    result = runner.invoke(main, ["airgap-probe-noflag"])
    assert result.exit_code == 0, result.output
    assert seen == [False]
