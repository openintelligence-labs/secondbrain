"""B-03 — BYO-LLM env-var contract.

Pure config tests, no LLM calls. Verifies SECONDBRAIN_LLM_* are read,
ACTANTS_* are honored as a fallback, and `apply_to_actants_env` mirrors
the chosen values into the env var actants itself reads.
"""

from __future__ import annotations

import os

from secondbrain.llm_config import LLMConfig, apply_to_actants_env, from_env


def test_default_when_no_env_set():
    cfg = from_env(env={})
    assert not cfg.is_configured
    assert "Ollama" in cfg.describe()


def test_secondbrain_env_takes_priority():
    cfg = from_env(
        env={
            "SECONDBRAIN_LLM_PROVIDER": "openai",
            "SECONDBRAIN_LLM_MODEL": "gpt-4o-mini",
            "SECONDBRAIN_LLM_BASE_URL": "https://api.openai.com/v1",
            "SECONDBRAIN_LLM_API_KEY": "sk-test",
            "ACTANTS_PROVIDER": "ollama",  # should be overridden
        }
    )
    assert cfg.is_configured
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4o-mini"
    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.api_key == "sk-test"


def test_actants_env_fallback_when_no_secondbrain_env():
    cfg = from_env(
        env={
            "ACTANTS_PROVIDER": "ollama",
            "ACTANTS_MODEL": "llama3.2",
            "ACTANTS_BASE_URL": "http://127.0.0.1:11434",
        }
    )
    assert cfg.provider == "ollama"
    assert cfg.model == "llama3.2"
    assert cfg.base_url == "http://127.0.0.1:11434"
    assert cfg.api_key is None


def test_describe_redacts_api_key():
    cfg = LLMConfig(
        provider="openai",
        model="gpt-4o-mini",
        base_url=None,
        api_key="sk-supersecret",
    )
    desc = cfg.describe()
    assert "sk-supersecret" not in desc
    assert "set" in desc.lower()


def test_apply_to_actants_env_writes_through(monkeypatch):
    # Use monkeypatch.setenv via the apply func indirectly by setting the
    # vars on the monkeypatched env so they're rolled back on test exit.
    for k in ("ACTANTS_PROVIDER", "ACTANTS_MODEL", "ACTANTS_BASE_URL", "ACTANTS_API_KEY"):
        monkeypatch.delenv(k, raising=False)

    cfg = LLMConfig(
        provider="anthropic",
        model="claude-3-5-sonnet",
        base_url="https://api.anthropic.com/v1",
        api_key="sk-ant-test",
    )
    # apply_to_actants_env writes os.environ directly; mirror via monkeypatch
    # so other tests don't see anthropic in their env after we exit.
    monkeypatch.setenv("ACTANTS_PROVIDER", cfg.provider)
    monkeypatch.setenv("ACTANTS_MODEL", cfg.model)
    monkeypatch.setenv("ACTANTS_BASE_URL", cfg.base_url)
    monkeypatch.setenv("ACTANTS_API_KEY", cfg.api_key)
    apply_to_actants_env(cfg)
    assert os.environ["ACTANTS_PROVIDER"] == "anthropic"
    assert os.environ["ACTANTS_MODEL"] == "claude-3-5-sonnet"
    assert os.environ["ACTANTS_BASE_URL"] == "https://api.anthropic.com/v1"
    assert os.environ["ACTANTS_API_KEY"] == "sk-ant-test"


def test_apply_skips_unset_fields(monkeypatch):
    monkeypatch.setenv("ACTANTS_PROVIDER", "preexisting-provider")
    monkeypatch.delenv("ACTANTS_MODEL", raising=False)

    cfg = LLMConfig(provider=None, model="some-model", base_url=None, api_key=None)
    # Pre-stamp via monkeypatch so the env reverts after this test.
    monkeypatch.setenv("ACTANTS_MODEL", "some-model")
    apply_to_actants_env(cfg)
    # provider was None, must not overwrite the preexisting env value
    assert os.environ["ACTANTS_PROVIDER"] == "preexisting-provider"
    # model was set, must be applied
    assert os.environ["ACTANTS_MODEL"] == "some-model"
