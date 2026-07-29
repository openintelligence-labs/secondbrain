# Redaction v0 — sensitive-frame detection

**Status:** draft, awaiting review
**Owner:** SecondBrain capture pipeline
**Target version:** 0.3

---

## 1. Problem

A SecondBrain user runs the capture daemon at 1 fps all day. Today the only thing standing between "1Password autofill flashed onscreen for 800 ms" and "that frame is now in your encrypted-but-permanent memory" is the **window-title deny-list** in `src/secondbrain/capture/deny_list.py`. That list catches:

- Apps that are *always* sensitive (1Password, Bitwarden, KeePass)
- Banking/healthcare *windows* matched by domain in the title bar

It misses the cases that actually happen:

| Scenario | Caught by deny-list? | Why not |
|---|---|---|
| Safari autofills a password into a checkout form | ❌ | Window title is "Checkout — Brand.com", not the password manager |
| iMessage shows an OTP code in a sidebar preview | ❌ | iMessage isn't on the deny-list (legitimate captures dominate) |
| Doc viewer with a tax return showing your SSN | ❌ | Title is the filename |
| Banking app rendered inside Brave (not on deny-list) | ❌ | Browser titles are arbitrary |
| Slack DM where someone pastes an API key | ❌ | Title is "Direct messages" |

The user has *only one* recourse today: `secondbrain forget --capture-id …` after the fact. That's GDPR-compliant but useless for the threat model — the leak already happened to anyone who pwned the encrypted DB key.

**Who has this pain.** Anyone who installs SecondBrain. The README pitches "captures, embeddings, KG, audit log never leave your device" — but the device itself is a vector. The redactor is what makes the privacy claim defensible when an attacker has filesystem access but not the key, and it's what makes the tool ethically shippable to non-technical users.

**Existing scaffolding.** `src/secondbrain/compliance/sensitive.py` already defines a `SensitiveClassifier` Protocol with a heuristic stub. The `[redact]` extra is referenced in the README but unwired. This spec covers wiring it.

---

## 2. Solution

A **single-stage VLM classifier** runs after the cheap dedup gates and before persist. It takes the surviving frame, classifies whether the visible content matches any of five categories (`password_field`, `otp_code`, `card_number`, `ssn`, `medical_record`), and either lets the frame through or replaces it with a redacted stub that records *why* without preserving content. The classifier is opt-in (`[redact]` extra + `--redact` flag or `SECONDBRAIN_REDACT=1`), runs entirely on-device, has a deterministic heuristic fallback when the model is unavailable, and every redaction event lands in the signed audit log so the user can prove later that the daemon refused to capture something.

We pick **Florence-2-base** (~230M params) over Moondream-3. Florence is one model load (~700 MB on disk), targets <200 ms p95 on M-series with `<CAPTION_TO_PHRASE_GROUNDING>` mode, MIT-licensed end-to-end (no Photon runtime ambiguity), and is *good enough* to recognize the five categories in v0 — we don't need Moondream's reasoning, we need a phrase grounder. Moondream's 2B parameter cost (~4× the wall-clock, ~6× the memory) buys richer free-form description we don't use in v0. We can swap Moondream in later behind the same `SensitiveClassifier` Protocol if Florence's false-negative rate proves too high on real captures.

---

## 3. Data model

Extend the existing `SensitiveDecision` in `src/secondbrain/compliance/sensitive.py` (today it has `is_sensitive`, `reason`, `confidence` — add `categories` and `model`).

```python
from typing import Literal
from pydantic import BaseModel, Field

SensitiveCategory = Literal[
    "password_field",   # visible password input or autofill prompt
    "otp_code",         # 4-8 digit code clearly labeled OTP/2FA/verification
    "card_number",      # 13-19 digit card-shaped number visible
    "ssn",              # 9-digit US-format SSN visible (XXX-XX-XXXX)
    "medical_record",   # diagnosis / prescription / patient ID visible
    "unknown",          # model said sensitive but couldn't pick a category
]

class SensitiveDecision(BaseModel):
    is_sensitive: bool
    confidence: float = Field(ge=0.0, le=1.0)
    categories: list[SensitiveCategory] = Field(default_factory=list)
    model: str = "heuristic"      # "florence-2-base" | "heuristic" | "deny-list"
    latency_ms: int | None = None  # wall-clock inference time

    # Reason is retained for backward compatibility with the existing Protocol
    # but is now a human-readable summary derived from `categories`.
    @property
    def reason(self) -> str:
        if not self.is_sensitive:
            return "clean"
        return ",".join(self.categories) if self.categories else "unknown"
```

A *redacted stub* — the row that lands in the OLTP store when a frame is redacted — uses the existing `Capture` model with these fields constrained:

```python
Capture(
    id=...,                          # normal capture ID — keeps audit-log linkage
    captured_at=...,                 # original frame timestamp
    app_name=...,                    # preserved (it's the deny-list/AX-tree value)
    app_bundle_id=...,               # preserved
    window_title="<redacted>",       # NEVER the original title
    ax_text=None,                    # AX text discarded
    image_b64=None,                  # pixel data discarded
    gate="redacted",                 # new gate name in the existing Literal
    meta={
        "redaction": {
            "categories": [...],
            "confidence": 0.94,
            "model": "florence-2-base",
            "latency_ms": 142,
        }
    },
)
```

Cascade `GateName` literal in `dedup.py` gains `"redacted"`. The audit-log entry shape (see §6) carries the full categories + confidence; the OLTP row only carries enough metadata to prove "this capture ID existed and was redacted" without re-leaking the title.

---

## 4. API design

This is a daemon-internal component — no external API. Surfaces:

### 4.1 Python interface (Protocol)

```python
class SensitiveClassifier(Protocol):
    def classify(
        self,
        image: Image.Image,
        *,
        hint: str = "",          # window title or app name — context only
        timeout_ms: int = 250,    # wall-clock cap; classifier should respect
    ) -> SensitiveDecision: ...
```

Two concrete implementations:

- `HeuristicClassifier` — already exists; updated to return the new `categories` field (always `[]` since it has no model).
- `FlorenceClassifier` — new; loaded behind `[redact]` extra.

### 4.2 Cascade integration

`DedupCascade.evaluate()` gains an optional injected `classifier: SensitiveClassifier | None`. When non-None and the frame survives all dedup gates, classifier runs *before* the `Decision(persist=True)` is returned. If the classifier says sensitive, the cascade returns `Decision(persist=False, gate="redacted", redaction=decision)`.

### 4.3 CLI surface

`secondbrain run` gains:

- `--redact` — enable the model-backed classifier (requires `[redact]` extra; clear error otherwise).
- `--redact-threshold FLOAT` — default 0.6; frames with `confidence < threshold` are *not* redacted (preserve recall).
- `--redact-categories LIST` — comma-separated; default `password_field,otp_code,card_number,ssn,medical_record` (all five).

### 4.4 Environment variables

- `SECONDBRAIN_REDACT=1` — equivalent to `--redact`.
- `SECONDBRAIN_REDACT_MODEL=florence-2-base` — currently the only value; reserved for future swaps.
- `SECONDBRAIN_REDACT_THRESHOLD=0.6`

### 4.5 Default behavior matrix

| `[redact]` extra | `--redact` flag / env var | Behavior |
|---|---|---|
| Not installed | Not set | No redaction (current behavior). |
| Not installed | Set | Daemon **refuses to start** with a clear error: "Redaction requested but [redact] extra not installed. Install with: pip install -e '.[redact]'" |
| Installed | Not set | No redaction. Heuristic classifier remains in `set_classifier()`. Log line at startup: "Redaction available but disabled (pass --redact to enable)." |
| Installed | Set | Florence loads at daemon start (~3s model load). Cascade injects it. |

**Note on the default.** We do *not* enable redaction by default even with the extra installed. Reason: model load adds 3s to daemon startup and ~700 MB of RAM; users should consciously opt in. The README will frame this as "if you want the daemon to be defensible against `cat ~/.secondbrain/secondbrain.db` after you lose your laptop, run with `--redact`."

---

## 5. Key algorithms

### 5.1 Where the gate fires

```
deny_list  (0 ms)       │  drops 1Password etc. — no need to run VLM
ax_unchanged (~1 ms)    │  drops "same AX tree as last frame"
dirty_rect (sidecar)    │  drops "<0.5% of pixels changed"
dhash (~0.3 ms)         │  drops near-identical frames
phash (~0.7 ms)         │
ssim (~5 ms)            │
─────────────────────────  ← redaction gate inserts HERE
redact (~150 ms p95)    │  runs Florence on frames that survived all of above
persist                 │  → encrypted OLTP + LanceDB + Kùzu
```

**Why this position.** Redaction is the most expensive gate by 30×; running it before dedup would waste compute on 90%+ of frames that get dropped anyway. Running it *after* persist (post-hoc, on a worker thread) would mean sensitive content briefly exists in the DB — defeats the threat model. Position 7 is the cheapest spot that still gates writes.

**Why not earlier than SSIM.** Two reasons. (1) SSIM is fast and drops most near-duplicates; redaction shouldn't pay the cost on them. (2) If a sensitive frame is *identical* to a frame we already redacted, the SSIM gate skips it correctly — the previous redaction is the answer.

### 5.2 Inference pseudocode

```python
def classify(image, hint, timeout_ms):
    if not self._loaded:
        self._load()  # one-shot; lazy

    # Florence's <CAPTION_TO_PHRASE_GROUNDING> task takes a prompt and
    # returns regions matching it. We run 5 prompts (one per category) and
    # take the max-confidence positive.

    prompts = {
        "password_field":  "a password input or autofill prompt",
        "otp_code":        "a one-time verification code",
        "card_number":     "a credit or debit card number",
        "ssn":             "a social security number formatted XXX-XX-XXXX",
        "medical_record":  "a medical diagnosis, prescription, or patient identifier",
    }

    deadline = now() + timeout_ms
    hits = []
    for category, prompt in prompts.items():
        if now() > deadline:
            return Decision(is_sensitive=False, confidence=0.0,
                            categories=[], model="florence-2-base-timeout",
                            latency_ms=int(now() - start))
        regions = self.model.run(image, task="grounding", prompt=prompt)
        if regions and max(r.score for r in regions) > self.threshold:
            hits.append((category, max(r.score for r in regions)))

    if not hits:
        return Decision(is_sensitive=False, confidence=0.0, categories=[],
                        model="florence-2-base", ...)

    categories = [c for c, _ in hits]
    confidence = max(s for _, s in hits)
    return Decision(is_sensitive=True, confidence=confidence,
                    categories=categories, model="florence-2-base", ...)
```

### 5.3 Model loading

Lazy, behind a `_load_lock`. First `classify()` call pays the ~3s cost. Daemon startup *triggers* the load in a background thread when `--redact` is set, so by the time the first frame arrives the model is ready (synchronous wait if not).

Disk cache via HF transformers default. Weights live under `~/.cache/huggingface/` — not inside the SecondBrain encrypted store (they're public model files; no privacy benefit to encrypting them, and SQLCipher would just bloat).

---

## 6. Error handling

| Failure | Detection | Behavior | Audit trail |
|---|---|---|---|
| `[redact]` not installed but `--redact` set | Import error on daemon start | **Refuse to start** with the install command in the error | n/a (daemon never started) |
| Model weights download fails (offline first run) | `OSError` from `from_pretrained` | **Refuse to start.** Do NOT silently fall back to heuristic — user opted in, we must not lie. | n/a |
| Model loaded but inference raises | `try/except Exception` around `model.run()` | **Fail closed:** treat as sensitive (`is_sensitive=True, categories=["unknown"], confidence=0.5, model="florence-2-base-error"`). Frame is redacted. | Audit log records the exception class+message. |
| Inference exceeds `timeout_ms` | Wall-clock check in the prompt loop | **Fail closed:** same as above with `model="florence-2-base-timeout"`. | Audit log records timeout. |
| Low confidence (below `--redact-threshold`) | Decision logic | **Fail open:** persist as normal. The threshold is the user's chosen recall/precision dial. | Audit log records the near-miss with confidence, for tuning. |
| Frame is `None` / corrupt PIL image | Pre-check at gate entry | Skip redaction; persist as normal (no decision). | Audit log records corrupt-frame event. |

**Fail-closed default rationale.** A redactor that fails open on errors is a redactor an attacker can DoS into uselessness by triggering errors. Failing closed costs us some recall (we drop frames we shouldn't have) but preserves the privacy invariant the user opted in for.

### 6.1 Audit log format

Every redaction (and every error that triggers fail-closed) writes an entry through `compliance/audit.py`. Existing `AuditLog.record(event, payload)` signature is reused:

```python
audit.record(
    event="redaction",
    payload={
        "capture_id": "01HZ...",          # the capture ID we discarded
        "captured_at": "2026-05-27T...",  # original frame timestamp
        "app_bundle_id": "com.apple.Safari",
        "categories": ["password_field"],
        "confidence": 0.94,
        "model": "florence-2-base",
        "latency_ms": 142,
        "threshold": 0.6,                 # what the user had it set to
    },
)
```

The entry is hash-chained with every other audit entry (existing behavior), so the user can later prove "between 2026-05-27 14:32 and 14:33, 7 frames were redacted as `password_field`." No image data, no AX text, no original window title — only metadata.

---

## 7. Testing plan

The hardest constraint: **the test suite must not ship copyrighted or genuinely sensitive content.** This means:

### 7.1 Synthetic fixture generation

Build a `tests/fixtures/redact/` directory of synthetic PNGs rendered at test time from `Pillow`-drawn text:

- `synth_password_field.png` — a rectangle with the label "Password" and dots
- `synth_otp_code.png` — text "Your verification code is 482913"
- `synth_card.png` — text "4111 1111 1111 1111  Exp 12/29"
- `synth_ssn.png` — text "SSN: 123-45-6789"
- `synth_medical.png` — text "Diagnosis: Hypertension, prescribed Lisinopril 10mg"
- `synth_clean.png` — text "Lorem ipsum dolor sit amet"

The card number and SSN are obvious test values (4111... is Visa's test PAN; 123-45-6789 is the canonical fake SSN). Documented as such inline in the fixture generator.

### 7.2 Test layers

| Layer | What it proves | Where |
|---|---|---|
| Unit: cascade gate position | `DedupCascade.evaluate` calls the classifier *after* SSIM, never before deny-list, and gates persist correctly | `tests/test_dedup_redact_gate.py` (no model — uses a mock classifier) |
| Unit: Decision shape | `SensitiveDecision` validates ranges, serializes correctly | `tests/test_sensitive_decision.py` |
| Unit: error handling | Timeout, inference exception, missing extra each produce the spec'd behavior | `tests/test_redact_failure_modes.py` (mock model that raises / sleeps) |
| Unit: audit linkage | A redacted frame writes one `audit.record(event="redaction")` entry with the spec'd payload | `tests/test_redact_audit.py` |
| Integration (gated): real Florence | When `SECONDBRAIN_TEST_REDACT_MODEL=1`, load Florence and run the 6 synthetic fixtures, assert each is classified per its filename | `tests/test_redact_florence_integration.py` |
| End-to-end (manual) | A real iMessage OTP / Safari autofill is redacted in a daemon run | Operator-run script, not in CI |

### 7.3 What CI runs

By default: everything except `test_redact_florence_integration.py` (it self-skips when `SECONDBRAIN_TEST_REDACT_MODEL` is unset). Same pattern as the Ollama-gated tests. This means CI proves the *integration* is correct without paying the model-download cost on every run.

### 7.4 Calibration plan (post-merge)

The synthetic fixtures don't tell us what real-world precision/recall look like. After v0 lands, run a calibration pass on a hand-curated set of ~200 real captures from the spec author's own machine (never committed). Document the resulting confusion matrix in the v0 retro. Adjust `--redact-threshold` default if needed.

---

## 8. Open questions

These need a decision before implementation:

1. **Florence's prompt set.** The five prompts in §5.2 are first-draft. Should they be tuned per-category (e.g. password_field benefits from "an input field labeled password or with masked dots")? — *Recommendation: ship v0 with the simple prompts and tune from calibration data.*

2. **Do we redact the AX text too?** A frame can be visually clean but the AX subtree contains the password value. v0 spec discards AX text on any visual redaction (safe default). Open question: should we run a *separate* AX-text regex pass (cheap) even when the visual classifier is off? — *Recommendation: out of scope for v0; tracked as a follow-up.*

3. **What about multi-monitor.** Today the daemon captures a single display. Redaction runs per-frame, so this is fine — but if multi-display lands, we need to confirm the classifier runs per-frame (per-display) not per-virtual-screen.

4. **Audit log retention vs. forget.** When the user runs `secondbrain forget --capture-id X`, does the redaction audit entry for X also get cascaded? — *Recommendation: NO. The forget cascade is for *captured* content; redaction proves we *didn't* capture, which is exactly the kind of provenance we want to retain forever. Document this.*

5. **Threshold default.** I picked 0.6. Real answer comes from calibration (Q1). v0 ships 0.6 and the README's "tune if it's too aggressive" footnote.

6. **Failure budget visibility.** If Florence is silently fail-closing on 20% of frames due to timeout, the user has no idea. — *Recommendation: `secondbrain status` gains a `redaction.errors_24h` counter. Out of scope for this spec but listed here so it's not forgotten.*

---

## 9. Out of scope for v0

Explicitly NOT in this spec — deliberate cuts to keep v0 shippable:

- **OCR-based regex redaction.** Tempting (regex for SSNs, card numbers via Luhn check) but adds a dependency on the Apple Vision sidecar OCR result, which is itself slow. Florence handles these visually. Revisit if Florence's recall on card numbers proves low.
- **Audio redaction.** The audio pipeline doesn't exist yet (it's roadmapped). When it lands, audio gets its own redactor spec.
- **Video segment redaction.** Captures are still frames at 1 fps. If we move to short video segments, segment-level redaction is a different design (temporal coherence matters).
- **Adversarial robustness.** A user crafting an image to evade the classifier is not in scope. Threat model is "ambient sensitive content during normal use," not "attacker on the user's machine."
- **Cloud-VLM fallback.** Hard local-only constraint. No "if Florence is too slow, send to OpenAI Vision."
- **Per-category threshold tuning in CLI.** All five categories share one threshold in v0. Per-category thresholds are a calibration follow-up.
- **Re-classification on demand.** Once a frame is redacted, the original is gone. No "show me what was here" recovery path — that would defeat the threat model.
- **Moondream-3 path.** Mentioned in the existing `sensitive.py` docstring but explicitly deferred. The Protocol makes swapping it in later trivial.

---

## 10. Rollout

1. PR 1 — pure scaffolding: extend `SensitiveDecision`, add the `redacted` gate to `DedupCascade`, wire `--redact` flag through CLI to daemon config. **No model.** Heuristic classifier still in place; tests prove the gate fires correctly.
2. PR 2 — `[redact]` extra in `pyproject.toml`, `FlorenceClassifier` implementation, model-load lifecycle, error handling per §6.
3. PR 3 — synthetic fixtures + integration test (gated), audit-log entries, README section.
4. PR 4 — calibration retro: real-world precision/recall numbers, threshold adjustment if needed, `secondbrain status` redaction counters.

Each PR is independently mergeable. PR 1 ships the contract; PRs 2–4 ship the implementation and the proof.

---

## 11. Decisions needed from you

Before I start PR 1:

- **§2 model choice — Florence-2-base.** Confirm or push back.
- **§4.5 default behavior.** "Installed but no flag" should log a startup line, not redact. Confirm.
- **§6 fail-closed on inference errors.** Confirm — this is the load-bearing privacy decision.
- **§7.4 calibration plan.** Are you OK with shipping v0 on synthetic fixtures only, with a real-world calibration retro post-merge?
- **§8 Q4 audit retention.** Confirm that `forget --capture-id X` does NOT delete the redaction audit entry for X.

If all five are "yes," I'll cut PR 1.
