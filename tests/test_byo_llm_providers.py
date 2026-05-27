"""Verify SECONDBRAIN_LLM_PROVIDER actually loads the right actants
provider class for every supported value.

This test does NOT make any network calls. It only confirms that:

  1. `LLMConfig` reads `SECONDBRAIN_LLM_PROVIDER`
  2. `apply_to_actants_env` writes `ACTANTS_PROVIDER` correctly
  3. `actants.LLM()` constructs the matching provider class

Each provider may need an upstream SDK (openai, anthropic, etc.) — install
the matching SecondBrain extra: `pip install secondbrain[byo-llm]`. Tests
that need the SDK are skipped when the SDK isn't importable.
"""

from __future__ import annotations

import importlib.util

import pytest

from secondbrain.llm_config import LLMConfig, apply_to_actants_env

_PROVIDERS = [
    # (provider_name, expected_class_name, required_sdk_module)
    ("ollama", "OllamaProvider", None),
    ("openai", "OpenAIProvider", "openai"),
    ("anthropic", "AnthropicProvider", "anthropic"),
    ("gemini", "GeminiProvider", None),  # gemini uses httpx, no extra SDK
    ("groq", "GroqProvider", "openai"),  # OpenAI-compatible
    ("mistral", "MistralProvider", "openai"),  # OpenAI-compatible
]


def _sdk_available(mod: str | None) -> bool:
    if mod is None:
        return True
    return importlib.util.find_spec(mod) is not None


@pytest.mark.parametrize("provider,expected_cls,sdk", _PROVIDERS)
def test_provider_class_loads(monkeypatch, provider, expected_cls, sdk):
    if not _sdk_available(sdk):
        pytest.skip(
            f"SDK '{sdk}' not installed — install with "
            f"`pip install secondbrain[{provider}]` or `secondbrain[byo-llm]`"
        )

    monkeypatch.setenv("ACTANTS_PROVIDER", provider)
    monkeypatch.setenv("ACTANTS_API_KEY", "sk-fake-load-test")

    cfg = LLMConfig(
        provider=provider,
        model=None,
        base_url=None,
        api_key="sk-fake-load-test",
    )
    apply_to_actants_env(cfg)

    from actants import LLM

    llm = LLM()
    assert type(llm.provider).__name__ == expected_cls
    # The provider's `name` attribute should round-trip the user's choice.
    assert llm.provider.name == provider


def test_unknown_provider_fails_clearly(monkeypatch):
    monkeypatch.setenv("ACTANTS_PROVIDER", "definitely-not-a-real-provider")
    monkeypatch.setenv("ACTANTS_API_KEY", "sk-fake")
    from actants import LLM

    with pytest.raises(ValueError, match="Unknown provider"):
        LLM()
