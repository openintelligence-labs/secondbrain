"""Biometric gate on forget: off by default, blocks on denial when enabled."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from secondbrain.compliance.biometric import BiometricDenied, confirm, is_required


def test_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("SECONDBRAIN_REQUIRE_BIOMETRIC", raising=False)
    assert is_required() is False
    # confirm() returns True without touching the binary.
    assert confirm("test") is True


def test_gate_on_but_helper_missing_raises(monkeypatch):
    monkeypatch.setenv("SECONDBRAIN_REQUIRE_BIOMETRIC", "1")
    with (
        patch("secondbrain.compliance.biometric._auth_binary", return_value=None),
        pytest.raises(BiometricDenied, match="not built"),
    ):
        confirm("test")


def test_gate_on_helper_succeeds(monkeypatch, tmp_path):
    # Forge a "helper" that returns 0.
    fake = tmp_path / "secondbrain-auth"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("SECONDBRAIN_REQUIRE_BIOMETRIC", "1")
    with patch("secondbrain.compliance.biometric._auth_binary", return_value=fake):
        assert confirm("test") is True


def test_gate_on_helper_denies(monkeypatch, tmp_path):
    fake = tmp_path / "secondbrain-auth"
    fake.write_text("#!/bin/sh\necho denied >&2; exit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("SECONDBRAIN_REQUIRE_BIOMETRIC", "1")
    with (
        patch("secondbrain.compliance.biometric._auth_binary", return_value=fake),
        pytest.raises(BiometricDenied, match="rc=1"),
    ):
        confirm("test")
