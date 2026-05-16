"""BYO-LLM env-var contract.

SecondBrain's positioning rule: captures stay local; the LLM transport is
pluggable. This module is the single place that reads the user's LLM
environment and produces an `actants.LLM` instance the rest of the code can
share.

Env vars (read in order; first non-empty wins):

    SECONDBRAIN_LLM_PROVIDER  → actants provider name (default: "ollama")
    SECONDBRAIN_LLM_MODEL     → model id              (default: actants's default)
    SECONDBRAIN_LLM_BASE_URL  → API base URL          (default: provider default)
    SECONDBRAIN_LLM_API_KEY   → API key for the provider, when needed

Compatibility: if SECONDBRAIN_LLM_* aren't set, we fall back to actants's
own ACTANTS_* env vars (it reads them anyway), so users who already
configured actants elsewhere don't have to re-configure it.

Provider support: `ollama` is the default and ships built-in. The five
hosted providers — `openai`, `anthropic`, `gemini`, `groq`, `mistral` —
work once the matching extra is installed (`pip install secondbrain[openai]`,
etc., or `secondbrain[byo-llm]` for all five). An unrecognised provider
name is forwarded to actants, which raises a clear error.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    provider: str | None
    model: str | None
    base_url: str | None
    api_key: str | None

    @property
    def is_configured(self) -> bool:
        return any((self.provider, self.model, self.base_url, self.api_key))

    def describe(self) -> str:
        if not self.is_configured:
            return "actants default (Ollama localhost)"
        bits = []
        if self.provider:
            bits.append(f"provider={self.provider}")
        if self.model:
            bits.append(f"model={self.model}")
        if self.base_url:
            bits.append(f"base_url={self.base_url}")
        if self.api_key:
            bits.append("api_key=*** (set)")
        return " ".join(bits)


def from_env(env: dict[str, str] | None = None) -> LLMConfig:
    """Read SECONDBRAIN_LLM_* (or fallback to ACTANTS_*) into an LLMConfig."""
    src = env if env is not None else os.environ

    def _pick(*keys: str) -> str | None:
        for k in keys:
            v = src.get(k)
            if v:
                return v
        return None

    return LLMConfig(
        provider=_pick("SECONDBRAIN_LLM_PROVIDER", "ACTANTS_PROVIDER"),
        model=_pick("SECONDBRAIN_LLM_MODEL", "ACTANTS_MODEL"),
        base_url=_pick("SECONDBRAIN_LLM_BASE_URL", "ACTANTS_BASE_URL"),
        api_key=_pick("SECONDBRAIN_LLM_API_KEY", "ACTANTS_API_KEY"),
    )


def apply_to_actants_env(cfg: LLMConfig) -> None:
    """Mirror SECONDBRAIN_LLM_* values into ACTANTS_* env vars so any
    `actants.LLM()` constructed downstream picks them up via its own
    `LLMSettings(BaseSettings)` reading.

    This is intentionally one-way: SECONDBRAIN_LLM_* is the user-facing knob;
    ACTANTS_* is the implementation detail it gets translated into.
    """
    if cfg.provider:
        os.environ["ACTANTS_PROVIDER"] = cfg.provider
    if cfg.model:
        os.environ["ACTANTS_MODEL"] = cfg.model
    if cfg.base_url:
        os.environ["ACTANTS_BASE_URL"] = cfg.base_url
    if cfg.api_key:
        os.environ["ACTANTS_API_KEY"] = cfg.api_key


def make_llm(cfg: LLMConfig | None = None):
    """Construct an `actants.LLM` honoring the user's BYO-LLM env."""
    cfg = cfg or from_env()
    apply_to_actants_env(cfg)
    from actants import LLM

    if cfg.model:
        return LLM(model=cfg.model)
    return LLM()
