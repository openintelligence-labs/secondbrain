"""Window-title deny-list — gate 1 of the dedup cascade.

Purpose: kill the entire class of "Recall got crucified for capturing my password
manager" frames at 0 ms before any pixel work. Built-in defaults cover password
managers, banking, healthcare, and 2FA confirmation prompts. User-extensible via
a YAML file.

Match semantics:
- Patterns are POSIX regex, compiled case-insensitive.
- A frame is denied if ANY pattern matches the *concatenation* of `app_name`
  and `window_title` (`app_name :: window_title`).
- `app_only` patterns match the app name in isolation (avoid matching anywhere
  in a long window title).

YAML format:
    deny:
      - 'pattern'
    deny_app_only:
      - 'app_pattern'
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# These defaults come from the architecture's "kill 80% of Recall-class frames
# at 0 ms before VLM" line. They are deliberately broad; users can pare back via
# the YAML override.
DEFAULT_DENY: list[str] = [
    # Password managers
    r"\b1Password\b",
    r"\bBitwarden\b",
    r"\bDashlane\b",
    r"\bLastPass\b",
    r"\bKeePass(XC)?\b",
    r"\bKeychain Access\b",
    r"\bProton Pass\b",
    # Banking / payments
    r"— (Chase|Wells Fargo|Bank of America|Citi|HSBC|Barclays|Capital One)\b",
    r"\bOnline Banking\b",
    r"\bStripe Dashboard\b",
    r"\bPayPal\b.*— (Send|Receive|Withdraw)",
    # Health
    r"\bTeladoc\b",
    r"\bMyChart\b",
    r"\bOne Medical\b",
    # 2FA / sensitive auth screens
    r"\b(2FA|Two-Factor|Authenticator)\b",
    r"\bSecurity Code\b",
    r"\bRecovery Phrase\b",
    r"\bSeed Phrase\b",
    # Tax
    r"\bTurboTax\b",
    r"\bH&R Block\b",
]

DEFAULT_DENY_APP_ONLY: list[str] = [
    r"^1Password( 7| 8)?$",
    r"^Bitwarden$",
    r"^Authenticator$",
    r"^Authy$",
    r"^Google Authenticator$",
    r"^Microsoft Authenticator$",
    # Never capture our own UI — without this, the daemon ingests its own
    # Timeline / Commitments panels and re-extracts memories from them,
    # producing recursive duplicates.
    r"^SecondBrain$",
    r"^secondbrain-app$",
]

# Bundle-ID-keyed deny patterns. Matched against `app_bundle_id` only.
# More robust than name matching because users can rename apps but the
# bundle id is set at signing time.
DEFAULT_DENY_BUNDLE_ID: list[str] = [
    r"^com\.openintelligencelabs\.secondbrain$",
]


@dataclass
class DenyList:
    """Compiled deny-list. `decide()` returns True when the frame must be denied."""

    deny: list[re.Pattern[str]] = field(default_factory=list)
    deny_app_only: list[re.Pattern[str]] = field(default_factory=list)
    deny_bundle_id: list[re.Pattern[str]] = field(default_factory=list)

    @classmethod
    def from_defaults(cls) -> "DenyList":
        return cls(
            deny=[re.compile(p, re.IGNORECASE) for p in DEFAULT_DENY],
            deny_app_only=[
                re.compile(p, re.IGNORECASE) for p in DEFAULT_DENY_APP_ONLY
            ],
            deny_bundle_id=[
                re.compile(p, re.IGNORECASE) for p in DEFAULT_DENY_BUNDLE_ID
            ],
        )

    @classmethod
    def from_yaml(
        cls,
        path: Path | str,
        *,
        merge_defaults: bool = True,
    ) -> "DenyList":
        """Load from YAML; merges over defaults unless `merge_defaults=False`."""
        data = yaml.safe_load(Path(path).read_text()) or {}
        deny = list(data.get("deny", []))
        deny_app_only = list(data.get("deny_app_only", []))
        deny_bundle_id = list(data.get("deny_bundle_id", []))
        if merge_defaults:
            deny = DEFAULT_DENY + deny
            deny_app_only = DEFAULT_DENY_APP_ONLY + deny_app_only
            deny_bundle_id = DEFAULT_DENY_BUNDLE_ID + deny_bundle_id
        return cls(
            deny=[re.compile(p, re.IGNORECASE) for p in deny],
            deny_app_only=[re.compile(p, re.IGNORECASE) for p in deny_app_only],
            deny_bundle_id=[re.compile(p, re.IGNORECASE) for p in deny_bundle_id],
        )

    def decide(
        self,
        app_name: str | None,
        window_title: str | None,
        app_bundle_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """Return (is_denied, reason). Reason is the matched pattern or None."""
        app = app_name or ""
        title = window_title or ""
        bundle = app_bundle_id or ""

        for pat in self.deny_bundle_id:
            if pat.search(bundle):
                return True, f"bundle:{pat.pattern}"

        for pat in self.deny_app_only:
            if pat.search(app):
                return True, f"app_only:{pat.pattern}"

        haystack = f"{app} :: {title}"
        for pat in self.deny:
            if pat.search(haystack):
                return True, pat.pattern

        return False, None
