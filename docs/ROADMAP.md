# SecondBrain — Roadmap

> Source of truth for **everything not yet done**. Per-story status, effort
> estimate, and the modules involved. Reviewed at the start of each session.
> When an item ships, move it to `IMPLEMENTATION.md` (where every `[x]` lives)
> and CHANGELOG.md.
>
> Status legend: `[ ]` not started · `[~]` partial · `[!]` blocked.

Last reviewed: **2026-07-29** · current version **v0.3.0** · **207 tests green**.

---

## Tier 1 — Blocks any non-developer user

These are the items between "a developer can clone and run" and "anyone can install."

| ID | Item | Status | Effort | Where |
|---|---|---|---|---|
| **D-01** | Code-sign + notarize a `SecondBrain.app` `.dmg` | `[ ]` | 2 days + Apple Developer ID ($99/yr) | `app/src-tauri/tauri.conf.json`, GitHub Actions release pipeline |
| **D-02** | Homebrew tap `brew install secondbrain` | `[ ]` | 0.5 day (after D-01) | new `homebrew-secondbrain` repo |
| **D-03** | First-run permissions wizard (Screen Recording + Accessibility prompt) | `[ ]` | 1 day | `app/src/main.ts` + Tauri `os` plugin |
| **D-04** | Without a signed bundle, every Swift rebuild revokes TCC. After D-01 this stops being a daily papercut. | `[!]` | depends on D-01 | macOS TCC behavior |

**Total Tier 1: ~3.5 days + Apple Developer ID.**

---

## Tier 2 — Marquee features currently shipping as stubs

The README claims these; the code today is interface-only.

| ID | Item | Status | Effort | Where |
|---|---|---|---|---|
| **S-01** | **Sensitive-content redactor.** Florence-2-base binary classifier (~80ms) + Moondream-3 mask generator. Today `compliance/sensitive.py` only flags when a hint is passed. | `[~]` interface ready | 2 days, ~3 GB models gated behind `secondbrain[redact]` | `compliance/sensitive.py`, `daemon.py` |
| **S-02** | **PaddleOCR-VL fallback** for dense documents when Apple Vision confidence <0.7. | `[~]` stub raises | 1 day, gated behind `secondbrain[ocr-vl]` | `ocr/paddleocr_vl.py`, `ocr/selector.py` |
| **S-03** | **Visual recall (ColQwen2.5) measured.** Embedder + store work; recall@10 on a curated 50-screenshot corpus has not been measured. Today the "find the slide with the red Q3 chart" claim is unproven. | `[~]` wired, never measured | 2 days for corpus + bench | `embed/visual.py`, `store/visual.py`, new `eval/visual_corpus/` |
| **S-04** | **Federated sync that actually syncs.** `SyncPolicy` enforces the contract; `IrohBackend.push` / `SyncthingBackend.push` raise `NotImplementedError`. No two devices have ever exchanged a fact. | `[~]` policy ✓, transport ✗ | 5 days (Iroh+Automerge), blocked on `iroh-blobs ≥1.0` stability | `sync/backend.py`, new `sync/automerge.py` |
| **S-05** | **RMM-retrospective** half of the reflection loop. The audit log captures the click signal; no learning reads it. | `[ ]` | 3 days | `memory/rmm.py` (new), reranker integration |
| **S-06** | **A-MEM retroactive note rewriting.** Linker writes KG edges; "Qwen3-8B rewrites neighbors" half not wired. | `[~]` linking ✓, rewrite ✗ | 2 days (after stable digest synthesizer) | `memory/amem.py` |

**Total Tier 2: ~15 days.** Pick the one that matters most for your story — I'd argue S-01 + S-03 together are the "GDPR + visual moat" demo bundle.

---

## Tier 3 — Cross-platform parity

| ID | Item | Status | Effort | Where |
|---|---|---|---|---|
| **X-01** | **Windows capture** via `windows-capture` Rust crate + PyO3. Needs a Windows runner. | `[~]` skeleton ✓, impl ✗ | 3 days (Windows host required) | `capture/windows_wgc.py` |
| **X-02** | **Windows AX (UIA3)** via `uiautomation` crate. | `[~]` stub | 1 day | `capture/ax_windows.py` |
| **X-03** | **Windows.Media.Ocr** wrapper. | `[~]` stub | 0.5 day | `ocr/windows_ocr.py` |
| **X-04** | **Linux capture** via PipeWire xdg-desktop-portal with persistent `RestoreToken`. | `[~]` skeleton ✓ | 2 days | `capture/linux_pw.py` |
| **X-05** | **Linux AT-SPI2** via `atspi-rs`. Coverage is GTK/Qt only. | `[~]` stub | 1 day | `capture/ax_linux.py` |
| **X-06** | **Linux OCR**: PaddleOCR-VL (GPU) + RapidOCR (CPU fallback). | `[~]` stub | 1 day | `ocr/paddleocr_vl.py`, new `ocr/rapid.py` |
| **X-07** | **CI matrix on Windows runner** (already green on macOS-14 + Ubuntu-24.04). | `[ ]` | 0.5 day after X-01 lands | `.github/workflows/ci.yml` |

**Total Tier 3: ~9 days** — gated on having Windows + Linux runners (CI or local).

---

## Tier 4 — UI half-finished or missing

Smaller items, each visible in the desktop app.

| ID | Item | Status | Effort | Where |
|---|---|---|---|---|
| **U-12** | `digest --llm` toggle actually flips the synthesizer. Today the button only changes the subtitle; gateway doesn't accept `use_llm`. | `[~]` UI ✓, wiring ✗ | 30 min | `api/http.py::digest`, `app/src/main.ts` |
| **U-13** | People panel sidebar listing all known persons (search-driven only today). | `[ ]` | 1 hour | `api/http.py` new `/people` route, `main.ts` |
| **U-14** | Audit log pagination. | `[ ]` | 2 hours | `api/http.py::audit_log`, `main.ts` |
| **U-15** | "Add note" composer in the UI. `/add-note` endpoint exists + is tested; no button calls it. | `[ ]` | 1 hour | `main.ts` Settings or sidebar |
| **U-16** | "Import wearable export" file picker (Plaud / OMI / Limitless / Bee / Rewind). | `[ ]` | 2 hours | Settings panel, `tauri-plugin-dialog` |
| **U-17** | "Export signed audit log" button in Settings. | `[ ]` | 30 min | `api/http.py` new `/audit/export`, button in UI |
| **U-18** | "Air-gap mode" toggle in Settings. The plumbing exists; no UI switch. | `[ ]` | 30 min | Settings, `compliance/air_gap.py` |
| **U-19** | Search overlay (`search.html`) vs in-panel Search — pick one. Currently both ship. | `[ ]` decision | 1 hour either way | `app/search.html`, `tauri.conf.json` |

**Total Tier 4: ~7 hours.**

---

## Tier 5 — Trust / eval / hardening

| ID | Item | Status | Effort | Where |
|---|---|---|---|---|
| **E-01** | **Real LongMemEval public-dataset run.** Synthetic 30-Q baseline shows 0.90; the credibility unlock is a public number. | `[~]` harness ready | 1 day | `eval/longmemeval.py`, HF dataset download |
| **E-02** | **LoCoMo public run.** | `[~]` harness ready | 1 day | `eval/replay.py` |
| **E-03** | **PerLTQA personal-profile probe.** | `[ ]` | 1 day | `eval/` |
| **E-04** | **Retention TTL sweeper.** Architecture promises "7 days raw HEVC, 90 days OCR + ColPali patches, ∞ embeddings + facts." Today captures live forever. | `[ ]` | 1 day | new `compliance/retention.py` + daemon task |
| **E-05** | **Air-gap CI test.** Real "run daemon under blocked network namespace" check. | `[ ]` | 2 hours | `.github/workflows/ci.yml` + a Linux job |
| **E-06** | **`secondbrain ui` thread teardown.** Gateway thread doesn't get explicit teardown when the Tauri binary exits. Cosmetic — Python tears it down on process exit. | `[ ]` | 15 min | `cli.py::ui` |
| **E-07** | **MCP-protocol e2e test** through stdio against the running gateway. Today we only test the in-process router. | `[ ]` | 2 hours | new `tests/test_mcp_stdio_live.py` |

**Total Tier 5: ~5 days.**

---

## Working agreements

- Pending items always live here. `IMPLEMENTATION.md` is for the done log.
- When an item ships, **delete it from this file** and add a row to `IMPLEMENTATION.md` + an entry in `CHANGELOG.md`.
- If a deferred item gets resurrected, it moves from the tier table back into in-progress in `IMPLEMENTATION.md`.
- New ideas land here first, with a tier + effort + module pointer. Don't start work until they're in the right tier.
- "Tier" is about *who's blocked*, not about how interesting the work is. Tier 1 ships things to actual users.

## Quick "what next?" guide

- **Goal: usable by a real person.** → Tier 1 (#D-01 first).
- **Goal: privacy story is provable.** → Tier 2 #S-01 (sensitive redactor) + #S-04 (sync).
- **Goal: visual recall is demoable, not just claimed.** → Tier 2 #S-03.
- **Goal: credible public eval number.** → Tier 5 #E-01.
- **Goal: polish the UI for a demo video.** → Tier 4 (~1 day total).
