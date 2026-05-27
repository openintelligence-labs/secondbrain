from __future__ import annotations

from pathlib import Path

from secondbrain.capture.deny_list import DenyList


def test_default_password_manager_denied():
    dl = DenyList.from_defaults()
    denied, reason = dl.decide("1Password 8", "All Vaults")
    assert denied is True
    assert reason is not None


def test_default_banking_window_title_denied():
    dl = DenyList.from_defaults()
    denied, _ = dl.decide("Safari", "Account Summary — Chase")
    assert denied is True


def test_default_innocuous_passes():
    dl = DenyList.from_defaults()
    denied, reason = dl.decide("Safari", "Hacker News")
    assert denied is False
    assert reason is None


def test_yaml_extends_defaults(tmp_path: Path):
    yaml_file = tmp_path / "deny.yaml"
    yaml_file.write_text(
        "deny:\n  - 'PaymentSystem Internal'\ndeny_app_only:\n  - '^MyCustomVault$'\n"
    )
    dl = DenyList.from_yaml(yaml_file)
    # User-supplied
    denied, _ = dl.decide("Safari", "PaymentSystem Internal Dashboard")
    assert denied is True
    denied, _ = dl.decide("MyCustomVault", "any title")
    assert denied is True
    # Default still active
    denied, _ = dl.decide("1Password 8", "any title")
    assert denied is True
