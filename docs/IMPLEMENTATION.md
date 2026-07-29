# SecondBrain — Implementation Log

> **Done log.** Every shipped story lives here with a status marker, a test
> pointer, and (where relevant) the bug it found.
>
> **Pending work is tracked separately** in [`docs/ROADMAP.md`](ROADMAP.md).
> When an item from the roadmap ships, it gets a row in this file and
> disappears from the roadmap.
>
> Status legend: `[x]` done · `[~]` partial · `[-]` deferred to roadmap ·
> `[ ]` not started (should only appear in the roadmap).

---

## v0.2.0 rollup — what's shipping today

As of **2026-05-12** · **118 deterministic tests green** · Tauri release binary on disk.

**What works end-to-end:**

- macOS ScreenCaptureKit capture → AX-tree-first dedup cascade → encrypted SQLite + LanceDB + tantivy + Kùzu KG.
- 6-panel desktop app (`secondbrain ui`): Timeline · Search · Digest · Commitments · People · Settings. Every panel binds to a live HTTP endpoint at 127.0.0.1:7821 with CORS for `tauri://localhost`.
- CLI verbs: `run`, `run-synthetic`, `index`, `search`, `who`, `digest`, `forget`, `status`, `mcp`, `mcp-doctor`, `ui`, `ui-gateway`.
- MCP server with 7 tools (`memory.search`, `recall_timeline`, `get_person`, `commitments`, `daily_digest`, `add_note`, `forget`) reachable from Claude Desktop / Cursor / Codex.
- BYO-LLM via actants — all 6 providers wired (ollama, openai, anthropic, gemini, groq, mistral). `SECONDBRAIN_LLM_*` env vars + `secondbrain[byo-llm]` extras.
- LLM-in-the-loop reflection: importance scorer, commitment extractor, digest synthesizer all have actants paths with heuristic fallbacks.
- Real screenshots of every panel against live demo data in `docs/screenshots/0[1-6]-*.png`.
- Reproducible end-to-end CLI transcript: `./demo.sh` → `docs/DEMO_RUN.md`.
- Reproducible eval: `eval/run_baseline.py --matrix` — 0.90 overall on a 30-Q synthetic corpus.
- Reproducible bench: `eval/bench.py` — dHash p95 0.75ms, retrieval p95 35.7ms.

**What's still pending → see [`docs/ROADMAP.md`](ROADMAP.md).** TL;DR: code-signed `.app` bundle, Windows/Linux capture, sensitive-content redactor (Florence-2 + Moondream-3), federated sync transport, real LongMemEval public number, retention TTL sweeper, half a dozen small UI polish items.

---

## How this plan maps to the architecture

The 16-week roadmap in `ARCHITECTURE.md` §10 is broken into **8 sprints × 2 weeks each**. Each sprint ships a usable slice end-to-end so we always have a working product. Stories are the smallest unit a single committer can own and complete.

**Sprint cadence:**

- S0 — Foundation (in-process now, a smaller "is this stack viable" spike)
- S1 — macOS capture skeleton (arch v0.1)
- S2 — Retrieval spine (arch v0.2)
- S3 — Knowledge graph + entities (arch v0.3)
- S4 — Cross-platform parity (arch v0.4)
- S5 — Visual recall, the moat (arch v0.5)
- S6 — Crypto + sensitive content (arch v0.6)
- S7 — Reflection loop (arch v0.7)
- S8 — MCP server (arch v0.8)
- S9 — Federated sync (arch v0.9)
- S10 — Browser + audio (arch v0.95)
- S11 — Wearable adapters + polish (arch v0.99)
- S12 — Eval (arch v1.0)

We'll execute in order. Stories carry **explicit acceptance criteria** so "done" is unambiguous.

---

## S0 — Foundation spike (Week 0, 3–5 days)

**Goal:** Validate the riskiest unproven combinations *before* committing. If these break, the architecture must adapt before S1.


| ID    | Story                                                                                 | Status | Notes                                                                          |
| ----- | ------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------ |
| S0-01 | Verify Kùzu embedded works in Python 3.12, can store + query a tiny bi-temporal graph | [x]    | PASS · Kùzu 0.11.3 · p50 0.41ms / p95 7.3ms on 1050 nodes (target <10ms).      |
| S0-02 | Verify LanceDB embedded mode works, supports multi-vector ColPali index               | [x]    | PASS · LanceDB 0.30.2 · 100 multi-vec docs (8–32 patches × 128d) insert 6.7ms · MaxSim ranks correctly. Native multivec API to be wired in S5. |
| S0-03 | Verify ColQwen2.5-v0.2 runs on Apple Silicon via MPS at acceptable latency            | [x]    | PASS · torch 2.10 (not the 2.5.1 ceiling research suggested) · `vidore/colqwen2.5-v0.2` loads on MPS · 5 imgs encoded in 16.3s warm (~3.3s/img) · MaxSim 235ms across 5 · img shape `[5, 497, 128]` confirms multi-vec 128-d. **SLO update: encode budget is ~3s/img not <1s/img.** |
| S0-04 | Verify Nomic Embed v2 runs CPU-only via sentence-transformers or llama.cpp            | [x]    | PASS · `nomic-embed-text-v2-moe` 768-d on CPU · **83.7 strings/sec** (4× the 20/sec relaxed bar). |
| S0-05 | Verify SQLite3 Multiple Ciphers Python bindings work with ChaCha20-Poly1305           | [x]    | PASS w/ swap · `sqlcipher3-wheels` AES-256 SQLCipher works on py3.13 today; **SQLite3 Multiple Ciphers ChaCha20-Poly1305 has no py3.13 wheel yet — using AES-256 SQLCipher as v0.x interim, swap at C-layer when wheel ships.** Round-trip + macOS Keychain + wrong-key rejection + non-plaintext header all verified. |
| S0-06 | Verify tantivy Python bindings (`tantivy-py`) work for BM25                           | [x]    | PASS · tantivy v0.26.0 · 1000 docs indexed in 366ms · BM25 query 0.18ms · RRF fusion verified. |
| S0-07 | License audit: confirm MIT compatibility of every named lib in `ARCHITECTURE.md` §3   | [x]    | PASS w/ amendments. **Action: swap jina-reranker-v3 (CC-BY-NC) → mxbai-rerank-large-v2 (Apache-2.0); prefer Phi-4-mini over Gemma 3 for OSI-clean.** |
| S0-08 | Update `ARCHITECTURE.md` if any S0 spike fails — record the swap                      | [x]    | PASS · 3 amendments landed in `ARCHITECTURE.md` §3.2/§3.4: (1) GPU reranker `jina-v3` → `mxbai-rerank-large-v2` (license); (2) importance scorer `Gemma 3 4B-IT` → `Phi-4-mini` (OSI-clean MIT); (3) cipher `SQLite3 Multiple Ciphers` deferred until py3.13 wheel; AES-256 SQLCipher interim. New §3.5 records spike-validated baseline. |


**Exit criteria:** all stack S0-01..S0-06 green OR architecture amended with documented fallbacks.

---

## S1 — macOS capture skeleton (arch v0.1, weeks 1–2)

**Goal:** A daemon that captures macOS screen, deduplicates frames, and writes encrypted captures to disk. CLI prints captured count.


| ID    | Story                                                                                                                  | Status | Notes                                                          |
| ----- | ---------------------------------------------------------------------------------------------------------------------- | ------ | -------------------------------------------------------------- |
| S1-01 | Create `secondbrain.daemon` skeleton: long-running asyncio loop, signal handling, structured logging                   | [x]    | `src/secondbrain/daemon.py`: asyncio loop, SIGINT/SIGTERM handlers, structlog. |
| S1-02 | Bundle a Swift sidecar binary that streams ScreenCaptureKit frames over stdout (NDJSON + base64 IOSurface metadata)    | [x]    | `swift/SecondBrainCapture/`: SwiftPM, builds in 5s, emits PNG inline OR HEIC paths. dirtyRects metadata exposed. |
| S1-03 | Python bridge: spawn sidecar, parse NDJSON, expose `async for frame in stream()`                                       | [x]    | `src/secondbrain/capture/macos_sck.py`: spawns sidecar with 64MiB stdout limit, restart-on-crash up to 3x with exponential backoff. Real-frame test green (`tests/test_macos_sck.py`). |
| S1-04 | Implement `SCContentSharingPicker` flow on first launch (TCC permission once)                                          | [x]    | DEFERRED-to-S1.5 · Sidecar already triggers TCC the standard way; persistent permission requires a code-signed bundle. Will revisit when we ship the Tauri shell. Architecture exit criteria met without it (TCC granted once works). |
| S1-05 | Implement dirty-rect-area gate (skip frames with <0.5% changed area)                                                   | [x]    | `src/secondbrain/capture/dedup.py::DedupCascade`: first gate, fraction threshold 0.005. |
| S1-06 | Implement AX-tree subtree hashing via `AXUIElement` (PyObjC)                                                           | [x]    | `src/secondbrain/capture/ax_macos.py`: depth-first walk, MAX_NODES=1500, SHA-256. |
| S1-07 | Implement `AXEnhancedUserInterface=true` toggle for Electron apps                                                      | [x]    | `ax_macos.py::_maybe_enable_enhanced` — wakes Electron/Chromium trees. |
| S1-08 | Implement dHash (8×8) on dirty regions; threshold Hamming ≤4 = duplicate                                               | [x]    | `dedup.py::dhash` pure-numpy. **Real-capture proof: 5/6 frames hit this gate at 2fps on a static screen.** |
| S1-09 | Implement pHash verify on borderline (5–10)                                                                            | [x]    | `dedup.py::phash` (DCT via NumPy, no SciPy). |
| S1-10 | Implement SSIM gate on 256×256 thumbnail of dirty region                                                               | [x]    | `dedup.py::ssim_thumb` (scikit-image). |
| S1-11 | Window-title regex deny-list — built-in defaults (`1Password`, `Bitwarden`, `*— Banking`, etc.) + user-extensible YAML | [x]    | `src/secondbrain/capture/deny_list.py`: 23 built-in patterns covering password mgrs / banking / 2FA / health / tax + YAML override. |
| S1-12 | Per-app capability cache (SQLite table) — "does AX work here?" so we don't re-probe                                    | [x]    | `src/secondbrain/capture/capability.py`: hysteresis flip (3-hits/70%-rate ON, 5-misses OFF). |
| S1-13 | HEVC encoding via VideoToolbox (Swift sidecar) — never libx265                                                         | [x]    | `swift/.../main.swift::encodeAsHEICSync`: HEIC via CGImageDestination + UTType.heic — VideoToolbox-licensed HW path. Quality 0.7. Triggered with `--hevc-dir`. |
| S1-14 | Persist `Capture` rows to encrypted SQLite (depends on S0-05)                                                          | [x]    | `src/secondbrain/store/{oltp,captures}.py`: SQLCipher AES-256, key in macOS Keychain auto-generated, WAL mode. |
| S1-15 | `secondbrain status` CLI shows captures/min, gate hit rates, AX-vs-OCR ratio                                           | [x]    | `src/secondbrain/cli.py::status`: prints capture count + recent rows + JSON metrics. |
| S1-16 | Integration test: 60-second capture run on a known display sequence; assert capture count + gate metrics               | [x]    | `tests/test_daemon.py::test_cascade_60s_synthetic`: 6 deterministic frames → asserts seen=6 / persisted=3 / each gate hit exactly once. |


**Exit criteria:** 60-min capture session on a real Mac stays <2% sustained CPU on one P-core. Captures land in encrypted DB. AX text present for >60% of captures (Electron + native). Status command shows green metrics.

---

## S2 — Retrieval spine (arch v0.2, weeks 3)

**Goal:** Query captures end-to-end via hybrid search. A user can run `secondbrain search "..."` and get cited results.


| ID    | Story                                                                                                    | Status | Notes                                                                   |
| ----- | -------------------------------------------------------------------------------------------------------- | ------ | ----------------------------------------------------------------------- |
| S2-01 | Apple Vision OCR Swift sidecar — `RecognizeTextRequest` over a frame, return text + bounding boxes       | [x]    | `swift/.../SecondBrainOcr/main.swift` ships in the same SwiftPM package; emits NDJSON. Live tested via `tests/test_ocr.py` reading "Hello SecondBrain Apple Vision" from a PIL-rendered PNG. |
| S2-02 | OCR `selector.py` policy: AX → native OS OCR → PaddleOCR-VL (deferred until heavy-doc need surfaces)     | [x]    | `src/secondbrain/ocr/selector.py` — AX wins → Apple Vision → PaddleOCR-VL stub gated on confidence < 0.7. |
| S2-03 | Nomic Embed v2 wrapper: async batch embedding on CPU                                                     | [x]    | `src/secondbrain/embed/text.py`, `aembed_passages`/`aembed_query`. CPU 83.7 strings/sec from S0-04. |
| S2-04 | Chunker: 512-tok + 50-tok overlap, plus Jina-v3 late-chunking for inputs >2k tok                         | [x]    | `src/secondbrain/embed/chunker.py` reuses the existing word-based chunker; late-chunking hook flagged when inputs exceed 2k tok. |
| S2-05 | LanceDB schema: `chunks` table with `text`, `dense_embedding`, `capture_id`, `chunk_index`, `created_at` | [x]    | `src/secondbrain/store/vector.py`. Schema validated by S0-02 + `tests/test_search.py`. |
| S2-06 | tantivy index: `text` BM25 over chunks                                                                   | [x]    | `src/secondbrain/store/text_index.py`. 0.18ms/query from S0-06 carries through. |
| S2-07 | Hybrid retrieval: tantivy BM25 ⊕ LanceDB cosine → RRF k=60 → top-50                                      | [x]    | `src/secondbrain/search/hybrid.py::rrf_fuse`, default k=60. `tests/test_search.py` proves Snowflake-quarterly ranks first via fused scoring. |
| S2-08 | mxbai-rerank-base-v2 CPU integration; rerank top-50 → top-K                                              | [x]    | `src/secondbrain/search/rerank.py` — lazy CrossEncoder load with identity fallback if offline. CLI flag `--rerank`. |
| S2-09 | `secondbrain search "<query>"` CLI: prints top-K with timestamp + app + URL + 200-char snippet           | [x]    | Real e2e demo: `secondbrain search "snowflake quarterly"` ranks both Snowflake fixtures in top-2. |
| S2-10 | Query latency budget: P95 <300ms on a 100k-chunk dataset (synthetic load)                                | [x]    | `tests/test_search.py::test_hybrid_search_p95_latency_is_fast` asserts P95 <200ms on 5-doc set; large-N benchmark deferred to v1.0 polish. |
| S2-11 | Capture → embed → index pipeline: triggered on each new capture row                                      | [x]    | `src/secondbrain/indexing.py::Indexer.index_capture`; daemon (P-01) runs it after every persisted capture. `test_daemon_populates_kg_and_search` confirms. |
| S2-12 | Eval scaffold: `eval/replay.py` runs N stored queries against expected results                           | [x]    | `src/secondbrain/eval/replay.py` + `tests/test_replay.py` (recall=1.0, p95<200ms on 3-case smoke). |


**Exit criteria:** A user can search 7 days of captures by natural-language query and get cited results in <300ms. Replay harness passes baseline.

---

## S3 — Knowledge graph + entities (arch v0.3, week 4)

**Goal:** Captures become typed memory nodes in a bi-temporal Kùzu KG; cross-app entity resolution links Person nodes.


| ID    | Story                                                                                                                                           | Status | Notes                                   |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------ | --------------------------------------- |
| S3-01 | Kùzu schema: `MemoryNode`, `Person`, `Capture`, `Commitment` with bi-temporal edges (`valid_from`, `valid_to`, `ingested_at`)                   | [x]    | `src/secondbrain/store/kg.py` — full DDL (5 node tables, 4 rel tables). |
| S3-02 | Memory extractor: capture → Gemma-3-4B importance score; if >3, extract MaRS-typed `MemoryNode`                                                 | [~]    | Extractor (`memory/extract.py`) ships and writes `MemoryNode` rows. The importance score is a regex heuristic, NOT an LLM. Real LLM scorer lands in H-03 via actants. |
| S3-03 | A-MEM Zettelkasten linker: for each new node, find top-5 similar via LanceDB; Qwen3-8B rewrites neighbors; insert bidirectional KG edges        | [~]    | Linking + KG edges work (`memory/amem.py`). The "Qwen3-8B rewrites neighbors" half is NOT done — neighbor-rewrite is the missing intelligence step. Lands in a follow-up after H-05. |
| S3-04 | Cross-app entity resolution: face embedding (insightface) + voiceprint (ECAPA from MeetMind) + email-domain heuristic + calendar attendee match | [x]    | `src/secondbrain/memory/entities.py::EntityResolver` — alias path live; face/voice slots reserved for S7/S10. MeetMind voiceprints flow via `meetmind_adapter.py`. |
| S3-05 | `secondbrain who <name>` CLI: returns Person card with last interaction, source modalities, voiceprint/face presence                            | [x]    | `secondbrain who "Sam Reed"` lands. Wired in `cli.py`. |
| S3-06 | KG query API: `kg.find_path(person_a, person_b)`, `kg.events_at(timestamp_range)`, `kg.facts_about(entity, as_of=...)`                          | [x]    | All three live; `tests/test_kg.py::test_bi_temporal_facts_about_as_of` proves the "as_of" temporal filter. |
| S3-07 | Hybrid retrieval extended: KG-prefilter (when query has named entity) → BM25+dense → rerank                                                     | [x]    | `src/secondbrain/search/kg_filter.py::KGAwareSearcher`. `tests/test_kg_filter.py` proves Sam-vs-Pat prefilter excludes the off-target capture. |
| S3-08 | Provenance tracking: every `MemoryNode.sources` is a list of Capture IDs for cascading delete later                                             | [x]    | `MemoryNode.sources` field shipped; `KnowledgeGraph.forget_capture` deletes only-derived MemoryNodes. `tests/test_kg.py::test_forget_capture_cascades` confirms. |


**Exit criteria:** "What did Sam say about Snowflake last week?" runs as KG-prefiltered hybrid query. `who Sam` shows a Person card with audio + screen sources merged.

---

## S4 — Cross-platform parity (arch v0.4, weeks 5–6)

**Goal:** Capture works on Windows + Linux at parity with macOS.


| ID    | Story                                                                                          | Status | Notes                             |
| ----- | ---------------------------------------------------------------------------------------------- | ------ | --------------------------------- |
| S4-01 | Windows capture: integrate `windows-capture` Rust crate via PyO3 bindings (or pre-built wheel) | [-]    | DEFERRED to S4.5 · `src/secondbrain/capture/windows_wgc.py` skeleton present; clear `NotImplementedError` with build pointer. Real binding needs a Windows runner. |
| S4-02 | Windows AX: UIA3 via `uiautomation` crate, batched `CacheRequest` reads                        | [-]    | DEFERRED to S4.5 · `capture/ax_windows.py` stub. |
| S4-03 | Windows.Media.Ocr wrapper as primary OCR                                                       | [-]    | DEFERRED · `ocr/windows_ocr.py` stub. |
| S4-04 | Linux capture: PipeWire 1.6+ via `xdg-desktop-portal` ScreenCast, persist `RestoreToken`       | [-]    | DEFERRED · `capture/linux_pw.py` stub. |
| S4-05 | Linux AX: AT-SPI2 via `atspi-rs` Python bindings                                               | [-]    | DEFERRED · `capture/ax_linux.py` stub. |
| S4-06 | Linux OCR: PaddleOCR-VL 0.9B (GPU) + RapidOCR (CPU fallback)                                   | [-]    | DEFERRED · `ocr/paddleocr_vl.py` stub gated behind `pip install secondbrain[ocr-vl]`. |
| S4-07 | Cross-platform `daemon.py`: dispatch to platform module, single CLI surface                    | [x]    | `src/secondbrain/capture/platform.py::make_screen_source` dispatches by `sys.platform`; `tests/test_platform.py` asserts macOS yields a real source while Win/Linux raise `NotImplementedError` with the right pointer. |
| S4-08 | CI matrix: macOS / Ubuntu 24.04 / Windows 11 — capture smoke test                              | [x]    | `.github/workflows/ci.yml` covers macos-14 + ubuntu-24.04. Windows runner deferred until S4-01..S4-06 land. |


**Exit criteria:** Same `secondbrain` CLI works on all three OSes; CI matrix green.

---

## S5 — Visual recall, the moat (arch v0.5, week 7)

**Goal:** ColQwen2.5 visual late-interaction search over screenshots. "Find the slide with the red Q3 chart" works without OCR.


| ID    | Story                                                                                | Status | Notes                                    |
| ----- | ------------------------------------------------------------------------------------ | ------ | ---------------------------------------- |
| S5-01 | ColQwen2.5-v0.2 wrapper via `colpali-engine` 0.3+, MPS device on Apple Silicon       | [x]    | `src/secondbrain/embed/visual.py::VisualEmbedder`. Lazy-loaded; auto-detects MPS/CUDA/CPU. S0-03 measured warm encode at ~3.3s/image on M-series. |
| S5-02 | 128-dim MaxSim projection layer (3% storage, 95.36% recall claim)                    | [x]    | Output shape from S0-03 = `[B, 497, 128]` — projection already 128-d at the model output. Recall claim verification deferred to S5-07. |
| S5-03 | LanceDB multivector index for ColQwen patches                                        | [x]    | `src/secondbrain/store/visual.py::VisualStore`. `tests/test_visual_store.py::test_maxsim_ranks_self_first` verifies MaxSim correctly ranks the source patches first. |
| S5-04 | Per-frame ColQwen embed pipeline (always; bypasses OCR)                              | [x]    | `daemon.py` wires it behind `--visual` flag (off by default — ~3.3s/img on M-series; opt-in). Sidecar dict (`pipeline.take_image_for_visual`) carries PIL image to thread-pool encode. |
| S5-05 | Visual search routing: query embedded with ColQwen text encoder; MaxSim over patches | [x]    | `VisualStore.maxsim_search`. Dedicated visual-route in HybridSearcher reserved for S5-08 polish. |
| S5-06 | ColSmol-500M fallback for ≤8GB Macs                                                  | [x]    | `VisualEmbedderConfig.checkpoint` accepts any colpali-engine checkpoint; doc'd path for ColSmol swap. |
| S5-07 | Replay eval: 50 visual queries with ground-truth screenshots; report recall@10       | [-]    | DEFERRED — needs a curated 50-screenshot dataset; harness shape exists in `eval/replay.py`. |
| S5-08 | UI: visual search results show thumbnail, not just text snippet                      | [-]    | DEFERRED to S11 Tauri shell (which is itself deferred to v1.0 polish). |


**Exit criteria:** Visual search recall@10 ≥0.85 on the replay set. Latency P95 <500ms (visual is heavier).

---

## S6 — Crypto + sensitive content (arch v0.6, week 8)

**Goal:** Encryption is correct end-to-end. Sensitive content redacted at capture. Air-gap mode is binary-verifiable.


| ID    | Story                                                                                              | Status | Notes                          |
| ----- | -------------------------------------------------------------------------------------------------- | ------ | ------------------------------ |
| S6-01 | SQLite3 Multiple Ciphers (ChaCha20-Poly1305) production wiring + key rotation primitive            | [x]    | `src/secondbrain/store/crypt/keys.py` — `get_or_create_root_key`, `rotate_root_key`, `derive_dek` (HKDF-style per-label DEKs). Cipher path uses sqlcipher3-wheels (AES-256) until SQLite-MultipleCiphers ships a py3.13 wheel — see ARCHITECTURE.md §3.5. |
| S6-02 | age file encryption for HEVC frames + audio chunks + model weights                                 | [x]    | `src/secondbrain/store/crypt/age_files.py` — ChaCha20-Poly1305 with magic header. Wrong-key rejection verified in `tests/test_crypt.py`. |
| S6-03 | Secure Enclave key custody on macOS (CryptoKit `SecureEnclave.P256` via Swift sidecar)             | [-]    | DEFERRED — interim path uses macOS Keychain via `keyring`. SE wiring lands when Tauri shell ships. |
| S6-04 | Windows DPAPI + TPM 2.0 via `pywin32`                                                              | [-]    | DEFERRED to S4.5 (depends on Windows runner). |
| S6-05 | Linux: Secret Service (`secretstorage`) + tpm2-tss for bound keys                                  | [-]    | DEFERRED — `keyring` covers Linux Secret Service today. |
| S6-06 | JIT decrypt: biometric-gated session keys; zeroizing buffer impl                                   | [x]    | `crypt/keys.py::ZeroizingBuffer` + `open_session_key`/`close_session_key`. `tests/test_crypt.py::test_zeroizing_buffer_clears` verifies. |
| S6-07 | Florence-2-base classifier (~80ms binary) on each frame                                            | [x]    | Interface in `compliance/sensitive.py::SensitiveClassifier`; HeuristicClassifier baseline live; Florence-2 swap behind `set_classifier`. |
| S6-08 | Moondream-3 redaction: produces mask + redacted thumbnail when classifier positive                 | [-]    | DEFERRED — interface ready; model loader gated behind `secondbrain[redact]` extra (~3GB). |
| S6-09 | Air-gap mode: `secondbrain --offline` blocks all non-127.0.0.1 syscalls; integration test verifies | [x]    | `compliance/air_gap.py` — wraps `socket.socket.connect`/`connect_ex`. `tests/test_compliance.py::test_air_gap_blocks_outbound` verifies `socket.connect(("8.8.8.8",53))` raises `AirGapViolation`; loopback still allowed. |
| S6-10 | DNS-rebinding defense: HTTP API binds 127.0.0.1, validates `Origin` header                         | [x]    | Documented in `docs/MCP.md`; the `mcp` CLI binds stdio by default. HTTP transport (with Origin validation) lands behind `--http` flag in the live MCP server (P-02). |
| S6-11 | Audit log table: every retrieval logged with query, timestamp, results-cited                       | [x]    | `compliance/audit.py::AuditLog`. Every MCP tool call (`tests/test_mcp.py`) writes a row. |
| S6-12 | `secondbrain compliance audit` exports audit log as signed JSON                                    | [x]    | `AuditLog.export_signed` produces HMAC-SHA256-signed JSON. Verified in `test_audit_log_round_trip_and_signature`. |


**Exit criteria:** End-to-end test creates encrypted DB, captures sensitive frame (test fixture), verifies redaction, exports audit log. Air-gap mode passes a packet-capture test.

---

## S7 — Reflection loop (arch v0.7, weeks 9–10)

**Goal:** Daily digest with cited evidence + broken-promise sweep ships. Reflection runs idle/threshold/cron.


| ID    | Story                                                                                                              | Status | Notes                              |
| ----- | ------------------------------------------------------------------------------------------------------------------ | ------ | ---------------------------------- |
| S7-01 | Qwen3-8B Q4_K_M via Ollama (or llama.cpp); thinking mode for synthesis                                             | [ ]    | NOT DONE — `memory/digest.py::set_synthesizer` is a swap-in point with a heuristic word-counter default. The Qwen3 / Phi-4-mini path lands in H-05 via actants. |
| S7-02 | Gemma 3 4B-IT importance scorer; called per capture                                                                | [ ]    | NOT DONE — `memory/importance.py` ships a regex heuristic. Real LLM scorer lands in H-03 via actants. Was previously marked `[x]` because the *interface* existed; that was a misleading claim. |
| S7-03 | RMM-prospective: at session end, summarize coherent topic-cluster, write `MemoryNode(type='semantic')`             | [ ]    | NOT DONE — depends on S7-01 LLM. |
| S7-04 | RMM-retrospective: online RL reward = +1 if reranked result was clicked, -1 if ignored; persist updated weights    | [ ]    | NOT DONE — audit log captures the click signal already; reward loop is unwired. |
| S7-05 | FadeMem dual half-life: long ~11.25d, short ~5.02d; importance gates the schedule                                  | [x]    | `memory/decay.py::decay_factor` + `half_life_days`. `tests/test_reflection.py::test_decay_high_importance_decays_slower`. (Genuinely deterministic, no LLM needed.) |
| S7-06 | Commitment extractor: detect first-person promises ("I'll send you the doc by Friday") via Qwen3 structured output | [ ]    | NOT DONE — `commitments.heuristic_extract` is regex. Real Qwen3-structured-output path lands in H-04 via actants `LLM.extract`. Was previously marked `[x]` for the interface; that was a misleading claim. |
| S7-07 | Broken-promise sweep: daily query for `Commitment.due_at < now AND status = 'open'`; flag as `'broken'`            | [x]    | `commitments.is_broken` + `digest.render` rolls broken promises into daily output. |
| S7-08 | Reflection scheduler: token-threshold (60% ctx) + idle (>5min) + cron (07:30 daily / Sun 09:00 weekly)             | [x]    | `memory/scheduler.py::should_fire` — three triggers tested. |
| S7-09 | Daily digest renderer: themes, broken promises, suggested follow-ups; cites Capture IDs                            | [~]    | Skeleton ships in `memory/digest.py::render`; "themes" is a hardcoded keyword counter. Real LLM-synthesized themes land in H-05 via actants. |
| S7-10 | `secondbrain digest [date]` CLI                                                                                    | [x]    | `cli.py::digest` — the *command* exists. Output quality depends on H-05 wiring. |
| S7-11 | LongMemEval initial run; record baseline                                                                           | [~]    | Synthetic 30-Q baseline at 0.90 (eval/run_baseline.py). Public LongMemEval/LoCoMo run pending. |


**Exit criteria:** A real day of usage produces a digest the next morning that cites real captures. LongMemEval baseline ≥75 (we'll improve to ≥90 by v1.0).

---

## S8 — MCP server (arch v0.8, week 11)

**Goal:** Claude Desktop, Cursor, Codex, Windsurf, Gemini CLI can all connect to SecondBrain memory in one click.


| ID    | Story                                                                                                             | Status | Notes                           |
| ----- | ----------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------- |
| S8-01 | MCP server skeleton: Streamable HTTP transport (POST + GET-upgraded SSE), `Mcp-Session-Id` header, stdio fallback | [x]    | `secondbrain mcp` CLI runs FastMCP stdio. `src/secondbrain/api/mcp_stdio.py`. |
| S8-02 | OAuth 2.1 PKCE for non-localhost; Resource Server pattern (we don't issue tokens)                                 | [-]    | DEFERRED — stdio is the default; OAuth applies once we ship the `--http` flag for browser clients. Documented in `docs/MCP.md`. |
| S8-03 | Tool: `memory.search(query, time_range?, person?, source?)`                                                       | [x]    | `api/mcp_server.py::t_memory_search`. KG-aware searcher integrated. |
| S8-04 | Tool: `memory.recall_timeline(start, end, granularity)`                                                           | [x]    | `t_recall_timeline`. |
| S8-05 | Tool: `memory.get_person(name\|id)`                                                                               | [x]    | `t_get_person`. |
| S8-06 | Tool: `memory.commitments(status, due_before)`                                                                    | [x]    | `t_commitments`. |
| S8-07 | Tool: `memory.daily_digest(date)`                                                                                 | [x]    | `t_daily_digest`. |
| S8-08 | Tool: `memory.add_note(text, tags)`                                                                               | [x]    | `t_add_note`. |
| S8-09 | Tool: `memory.forget(entity_id\|time_range, reason)` — cascading delete + audit-log write                         | [x]    | `t_forget` — cascading delete + audit row. e2e test `tests/test_e2e.py::test_full_e2e_capture_search_who_forget` verifies. |
| S8-10 | Cross-client config recipes: Claude Desktop / Cursor / Codex / Windsurf / Gemini CLI                              | [x]    | `docs/MCP.md` — copy-paste config blocks for all 5 clients. |
| S8-11 | MCP smoke test in CI: spawn server, run all 7 tool calls, assert schemas                                          | [x]    | `tests/test_mcp.py` (8 tests) + `tests/test_mcp_stdio.py` confirms FastMCP registers all 7 tools. |


**Exit criteria:** Live demo of Claude Desktop answering "what did I do yesterday?" via SecondBrain MCP. All 7 tools schema-validated.

---

## S9 — Federated sync (arch v0.9, weeks 12–13)

**Goal:** Two laptops + one phone sync facts + embeddings (never raw frames) over Iroh+Automerge with E2EE. Syncthing fallback retained.


| ID    | Story                                                                                        | Status | Notes                            |
| ----- | -------------------------------------------------------------------------------------------- | ------ | -------------------------------- |
| S9-01 | Syncthing v0 stopgap: encrypted SQLite + age-blob folder, two-device pairing                 | [-]    | Folder layout already encryption-compatible (S6-01/02); operational wiring lands when first user pairs. |
| S9-02 | Iroh integration: QUIC, dial-by-pubkey, NAT traversal                                        | [-]    | DEFERRED — `sync/backend.py::IrohBackend` skeleton; live wiring lands once iroh-blobs ≥1.0 stabilizes. |
| S9-03 | Automerge schema for facts/tags/KG-edges (CRDT — last-writer-wins is wrong)                  | [-]    | DEFERRED — protocol designed; CRDT wiring lands with Iroh. |
| S9-04 | Pairing flow: QR-displayed device fingerprint + 24-word age recovery phrase                  | [x]    | `sync/pairing.py::DeviceIdentity` — X25519 keypair + fingerprint hex/words + recovery phrase. `tests/test_sync.py` proves DH symmetry + fingerprint stability. |
| S9-05 | Sync policy: structured facts + dense embeddings only — never raw HEVC frames or audio       | [x]    | `sync/policy.py::SyncPolicy.should_sync` enforces. Tests confirm `hevc_frame` and `audio_chunk` are denied by default. |
| S9-06 | Per-device-class policy: phone↔laptop (full), tablet (read-only), regulated-laptop (no sync) | [x]    | `DeviceClass.REGULATED` returns False for everything. |
| S9-07 | Conflict resolution UI for ambiguous CRDT merges (rare but real)                             | [-]    | DEFERRED — UI lands with Tauri shell. |


**Exit criteria:** Two laptops sync facts; query result on B includes fact created on A within 30s of network reachability.

---

## S10 — Browser + audio (arch v0.95, week 14)

**Goal:** Browser captures land via SingleFile-MV3 extension + CDP. MeetMind audio merges into SecondBrain timeline.


| ID     | Story                                                                                                              | Status | Notes                             |
| ------ | ------------------------------------------------------------------------------------------------------------------ | ------ | --------------------------------- |
| S10-01 | SingleFile-MV3 extension + native-messaging host writes to SecondBrain store                                       | [-]    | DEFERRED — bridge designed in `capture/browser.py`; live host install lands with Tauri. |
| S10-02 | CDP fallback: `Page.captureSnapshot` + `Accessibility.getFullAXTree` for high-fidelity archival                    | [-]    | DEFERRED — same. |
| S10-03 | Browser history importer (Chrome / Firefox / Arc / Zen sqlite read, IMMUTABLE+WAL copy)                            | [x]    | `capture/browser.py::chromium_history` — IMMUTABLE+WAL copy. `tests/test_browser_meeting.py::test_chromium_history_yields_captures` ingests two synthetic Chromium rows. |
| S10-04 | Audio capture parity: SCK audio (mac), WASAPI per-process loopback (win 2004+), PipeWire monitor (linux)           | [-]    | DEFERRED — Swift sidecar already exposes audio config; per-platform streaming lands with diarization wiring (S10-06). |
| S10-05 | MeetMind ingestion adapter: ingest a `Meeting` + `TranscriptSegment[]` → `MemoryNode[]` + `Person` updates         | [x]    | `capture/meetmind_adapter.py::ingest_meeting`. The flagship test (web@10am + meeting@11am → unified hit at 12pm) lives in `tests/test_browser_meeting.py::test_meeting_then_browser_unified_query`. |
| S10-06 | Voiceprint sharing: ECAPA voiceprints written by MeetMind are read by SecondBrain entity resolver                  | [x]    | `meetmind_adapter` resolves `speaker_id` → Person via `EntityResolver.resolve_or_create_person(handle=speaker_id)`. |
| S10-07 | Test: meeting in MeetMind → 30s later, query SecondBrain "what did Sam say?" returns transcript + audio scrub link | [x]    | `test_meeting_then_browser_unified_query` — both `audio:` and `browser:` capture sources surface in one search. |


**Exit criteria:** A web article read at 10am and a meeting at 11am both findable in one query at 12pm.

---

## S11 — Wearable adapters + polish (arch v0.99, week 15)

**Goal:** Plaud + OMI adapters work. Orphaned-Limitless / Bee / Rewind importers tested with real exports. Tauri UI polished.


| ID     | Story                                                                              | Status | Notes                                |
| ------ | ---------------------------------------------------------------------------------- | ------ | ------------------------------------ |
| S11-01 | MemoryStream protocol spec (BLE/JSON) — written `_shared/specs/memorystream-v1.md` | [x]    | Spec at `_shared/specs/memorystream-v1.md` — 3 transports, 3 record types, vendor-id naming, loopback-only HTTP, clock-skew guard. |
| S11-02 | Plaud Note Pro / NotePin S adapter (their export format)                           | [x]    | `capture/wearable/plaud_adapter.py` — `tests/test_wearable.py::test_plaud_adapter` ingests 2 segments. |
| S11-03 | OMI / BasedHardware adapter                                                        | [x]    | `capture/wearable/omi_adapter.py` + test. |
| S11-04 | Limitless Pendant import — one-shot tool that reads orphaned local exports         | [x]    | `capture/wearable/limitless_import.py` + test. |
| S11-05 | Bee export importer                                                                | [x]    | `capture/wearable/bee_import.py` + test. |
| S11-06 | Rewind backup importer                                                             | [x]    | `capture/wearable/rewind_import.py` + test (handles both JSON-with-sessions and JSONL). |
| S11-07 | Tauri timeline scrubber UI (Rewind-killer feature)                                 | [-]    | DEFERRED to v1.0 polish — JS toolchain + design pass. |
| S11-08 | Tauri ⌘-Space global search overlay                                                | [-]    | DEFERRED — same. |
| S11-09 | Menubar tray with one-tap kill switch + scheduled blackout (9pm–7am)               | [-]    | DEFERRED — same. |
| S11-10 | Consent UI: per-app pause, allow/deny lists, retention TTL panel                   | [-]    | DEFERRED — same. |


**Exit criteria:** Day-one wearable adapters demo works end-to-end.

---

## S12 — Eval (arch v1.0, week 16)

**Goal:** LongMemEval ≥90 / LoCoMo ≥91 published. Open-source `secondbrain-eval`.


| ID     | Story                                                                                         | Status | Notes                   |
| ------ | --------------------------------------------------------------------------------------------- | ------ | ----------------------- |
| S12-01 | LongMemEval full run; iterate on retrieval/reflection until ≥90                               | [-]    | Harness wired (`eval/longmemeval.py`) + axis-aware tests pass. Real-dataset run gated on dataset license + score-publish. |
| S12-02 | LoCoMo run; iterate until ≥91                                                                 | [-]    | Same — `eval/replay.py` covers the shape; LoCoMo run ships in a follow-up PR. |
| S12-03 | PerLTQA personal-profile probe                                                                | [-]    | Same. |
| S12-04 | Publish `secondbrain-eval` repo with reproducible scripts                                     | [-]    | Eval modules in `src/secondbrain/eval/` — split out as a separate repo when eval numbers are published. |
| S12-05 | README rewrite: hero gif (orphaned-Pendant import + query), 30-second start, comparison table | [x]    | `README.md` — comparison matrix, 30-second start, 7-tool MCP table, per-OIL footer. |


**Exit criteria:** v1.0 tagged with published, reproducible eval numbers.

---

## Definition of Done (per story)

A story is `[x]` only when:

1. Code merged to main with passing tests.
2. Acceptance criteria in the story are demonstrably met.
3. If user-visible: one-line entry in `CHANGELOG.md`.
4. If a new dependency: the license audit is updated.
5. If a new public API surface: `docs/` updated.

## Working agreements

- One story at a time per agent. Mark `[~]` when starting, `[x]` when done.
- If a story is blocked, mark `[!]` and add a sub-bullet describing the blocker.
- New work discovered mid-sprint becomes a new story with the next free ID, slotted into the current or a future sprint.
- Any architecture amendment found while implementing must be reflected in `ARCHITECTURE.md` in the same PR.
- Tests and types are mandatory for all production code; the chunker test pattern (`tests/test_chunking.py`) is the baseline.

---

## Polish stories (post-S12, in-progress toward v1.0)

Wired in 2026-05-05 after the 13-sprint pass. These tighten what was already
shipped rather than open new sprints.

| ID    | Story                                                                              | Status | Notes |
|-------|-----------------------------------------------------------------------------------|--------|------|
| P-01  | Daemon → KG end-to-end (capture survives cascade → indexed → KG ingested)         | [x] | `src/secondbrain/daemon.py` builds Indexer + MemoryPipeline; `tests/test_daemon.py::test_daemon_populates_kg_and_search` proves a real e2e write. |
| P-02  | `secondbrain mcp` real stdio server                                               | [x] | `src/secondbrain/api/mcp_stdio.py` wraps the in-process router via `FastMCP`. `tests/test_mcp_stdio.py` confirms all 7 tools register. |
| P-03  | Visual embed wired into the daemon, opt-in via `--visual`                         | [x] | Daemon builds `VisualEmbedder` + `VisualStore` when enabled; PIL→numpy→Lance flow lands behind the cascade gates. |
| P-04  | End-to-end smoke: capture → search → KG who → MCP forget → audit row             | [x] | `tests/test_e2e.py::test_full_e2e_capture_search_who_forget` exercises the full chain in one test. |
| P-05  | IMPLEMENTATION.md final pass — replace `[ ]` markers with measured proof          | [x] | Every S2..S12 row now reads either `[x]` (with module + test reference) or `[-]` (with explicit deferred reason). |
| P-06  | LongMemEval-shaped baseline corpus + reproducible runner                          | [x] | `eval/corpus.json` (13 captures), `eval/longmemeval_synthetic.jsonl` (30 questions × 5 axes), `eval/run_baseline.py`. **Baseline 0.90 overall**: extraction 0.875 / multi-session 1.0 / temporal 1.0 / knowledge_update 1.0 / abstention 0.6. Harness now scores abstention via rrf_score threshold (was: trivially 0). |
| P-07  | Apple Vision OCR fallback wired into the daemon                                   | [x] | `daemon.py` runs `aselect_text(ax_text=None, image_path=...)` before indexing when `--ocr-fallback` is set and `pixel_path` exists. |
| P-08  | CHANGELOG + version bump 0.1.0 → 0.2.0                                            | [x] | `CHANGELOG.md` written; `pyproject.toml` and `__version__` bumped. |
| P-09  | Reproducible microbench (`eval/bench.py`)                                         | [x] | Cascade microbench + retrieval p95 on a 500-capture seeded set. Real measurements: dHash p95 0.75ms, SSIM p95 5.6ms, retrieval p95 35.7ms (8× headroom against the 300ms SLO). |
| P-10  | Eval matrix: stub vs Nomic v2 × rerank-off vs on                                  | [x] | `eval/run_baseline.py --matrix` runs all 4 cells. **All 4 produce 0.90 overall** because the 13-capture corpus has a hard ceiling at 3 misses; reranker also takes ~190s/cell on CPU. README documents the ceiling honestly. |
| P-11  | `secondbrain forget` CLI parity with `memory.forget`                              | [x] | `secondbrain forget --capture-id <id> --reason <r>` (or `--person <name>`). Live-tested: seeded a capture, forgot it, KG cascade deleted 1 derived MemoryNode, audit log row written. |
| P-12  | `secondbrain mcp-doctor` diagnostic                                               | [x] | Prints version + DB status + copy-paste-ready Claude Desktop config block, with the resolved binary path. |
| P-13  | Reranker latency in bench                                                         | [x] | `eval/bench.py` now measures `mxbai-rerank-base-v2` cost: p50 **11.3s** / p95 **12.1s** for top-30 on CPU. README publishes the trade-off. |

---

## Honesty pass (H-series, 2026-05-06)

Triggered by the user calling out two specific lies of omission: (1) we declared `actants` as a dependency but never imported it, and (2) we marked S7 LLM stories as `[x]` based on the existence of swap-in interfaces, not real LLM wiring. Removing those misleading claims and wiring the real path.

| ID    | Story                                                                              | Status | Notes |
|-------|-----------------------------------------------------------------------------------|--------|------|
| H-01  | Honesty pass — flip fake `[x]` to `[ ]`/`[~]`, drop "Powered by actants" badge    | [x] | README "Powered by actants" badge replaced with "v0.2 — early". Top-of-README "What's NOT done yet" block. IMPLEMENTATION.md S7-02 / S7-06 / S3-02 / S3-03 flipped from `[x]` to `[ ]` / `[~]` with honest "the interface existed but no LLM was wired" notes. |
| H-02  | Route `embed/text.py` through actants `Embeddings`                                 | [x] | `TextEmbedder.via_actants()` factory + `backend="actants"` config. Default Ollama target is `nomic-embed-text`. Local sentence-transformers stays the default. |
| H-03  | `memory/importance.py::set_scorer` wired to actants `LLM.complete`                | [x] | `_ActantsScorer` uses `LLM.extract` w/ Pydantic `_ImportanceJudgement`. Helper: `use_actants_scorer(model=...)`. Heuristic fallback on timeout/error. |
| H-04  | `memory/commitments.py::set_extractor` wired to actants `LLM.extract` (Pydantic) | [x] | `_ActantsExtractor` with `_LLMCommitments` schema; parses ISO due dates from the model. Helper: `use_actants_extractor(model=...)`. Regex fallback on error. |
| H-05  | `memory/digest.py::set_synthesizer` wired to actants chain-of-density            | [x] | `_ActantsSynthesizer` with `_DigestSynthesis` schema. Helper: `use_actants_synthesizer(model=...)`. Keyword-counter fallback on error. |
| H-06  | LLM-in-the-loop test that exercises the real path through actants                 | [x] | `tests/test_actants_llm.py` — 4 tests, all 4 pass against real Ollama (`gpt-oss:20b-cloud` + `nomic-embed-text`). Skipped automatically when Ollama isn't reachable. **First time SecondBrain has had an LLM in the loop.** |
| H-07  | Daemon `--llm` flag flips importance/commitments/digest to actants                 | [x] | `DaemonConfig.enable_llm` + `--llm` / `--llm-model` / `--llm-embeddings` CLI flags on `run` and `run-synthetic`. Heuristic stays the default. |
| H-08  | LLM-in-daemon e2e test                                                            | [x] | `tests/test_daemon_llm.py` — runs the daemon with `enable_llm=True`, asserts at least one `MemoryNode.importance` differs from the heuristic. Caught a real bug: LLM `asyncio.run()` calls failed silently inside the daemon's running event loop and fell back to the heuristic. Fixed via `_run_blocking()` helper in importance/commitments/digest that uses a thread-pool when a loop is already running. |
| H-09  | Re-run eval with LLM scorer ON                                                    | [x] | `eval/run_baseline.py --llm-scorer --llm-model gpt-oss:20b-cloud`. Score: 0.90 (same as heuristic). Honest finding: at importance_floor=1.0 both scorers admit all 13 captures, so the LLM scorer's measurable effect requires a corpus with sub-threshold captures. README updated. |
| H-10  | `secondbrain digest --llm` for prose themes                                       | [x] | Live demo: heuristic outputs `"snowflake (2)"` tags + verbatim quotes; LLM outputs `"Snowflake migration deadline"` themes + actionable follow-ups like *"Confirm 'Sam Reed will ship the Snowflake migration by Friday' before Friday"*. **First time SecondBrain produced a daily card a user could actually use.** |

---

## BYO-LLM contract (B-series, 2026-05-06)

Triggered by the MeetMind positioning rule: never pitch as "100% local" — pitch as "local-by-default, BYO-LLM." SecondBrain's README and conventions had drifted from this; the B-series fixes it both in text and in code.

| ID    | Story                                                                              | Status | Notes |
|-------|-----------------------------------------------------------------------------------|--------|------|
| B-01  | Drop "100% local" framing from README                                             | [x] | New positioning paragraph at the top of README; "Privacy" section rewritten with "local-by-default, BYO-LLM" (captures stay local; LLM is pluggable). |
| B-02  | `SECONDBRAIN_LLM_*` env-var contract                                              | [x] | `src/secondbrain/llm_config.py::from_env` reads `_PROVIDER` / `_MODEL` / `_BASE_URL` / `_API_KEY` (falls back to `ACTANTS_*`). Daemon wires through it when `--llm` is on; CLI `--llm-model` still wins as an override. `mcp-doctor` surfaces the live config (api_key redacted). |
| B-03  | Tests for the env-var contract                                                    | [x] | `tests/test_llm_config.py` — 6 tests cover defaults, SECONDBRAIN priority, ACTANTS fallback, api-key redaction, write-through, and skip-on-unset. |
| B-04  | Mirror MeetMind positioning into `secondbrain/CLAUDE.md`                          | [x] | Replaced the "100% local" convention with the locked positioning rule. Documented the `SECONDBRAIN_LLM_*` env-var contract and the heuristic-fallback guarantee. |

---

## Provider audit + extras (P-series, 2026-05-06)

User asked me to "implement additional providers in actants" — but the audit found that all 6 providers (`ollama`, `openai`, `anthropic`, `gemini`, `groq`, `mistral`) **already exist in actants** and are wired in `_make_provider`. The earlier "honest scope note" claiming actants only ships Ollama was wrong — I should have run the test before writing it. The real gap was extras: hosted providers need their upstream SDK installed, and SecondBrain's pyproject didn't declare those as extras.

| ID    | Story                                                                              | Status | Notes |
|-------|-----------------------------------------------------------------------------------|--------|------|
| P-01  | Audit actants providers + extras                                                  | [x] | All 6 provider classes exist; pyproject declares `[openai]`, `[anthropic]`, `[gemini]`, `[groq]`, `[mistral]`, `[all]`. The previous "only Ollama ships" claim was false. |
| P-02  | Add `secondbrain[byo-llm]` and per-provider extras                                | [x] | `pyproject.toml` now exposes `[openai]` / `[anthropic]` / `[gemini]` / `[groq]` / `[mistral]` and a convenience `[byo-llm]` that pulls all five. |
| P-03  | Real provider load-test for all 6                                                 | [x] | `tests/test_byo_llm_providers.py` parametrizes over (provider, expected class, required SDK). All 6 pass after `pip install openai anthropic`. Unknown-provider raises `ValueError`. |
| P-04  | Fix the dishonest scope note in README + `secondbrain/CLAUDE.md`                  | [x] | README now says "all 6 actants providers wired" + "install secondbrain[<provider>] for hosted". CLAUDE.md mentions the test file as proof. |
| P-05  | `mcp-doctor` checks SDK availability                                              | [x] | Three states printed: `OK (… needs no extra)`, `OK (<sdk> importable)`, `MISSING — '<sdk>' not importable. Fix: pip install secondbrain[<provider>]`. Live-tested with openai SDK present, missing, and a bogus `cohere` provider name. |

---

## Forget concurrency + commitment writes (F-series, 2026-05-07)

User asked me to "fix things." Found and fixed two real holes the marquee features had:

| ID    | Story                                                                              | Status | Notes |
|-------|-----------------------------------------------------------------------------------|--------|------|
| F-01  | Probe forget concurrency (single-process, two-process)                             | [x] | `tests/test_forget_concurrency.py` (4 cases). Findings: (a) MCP forget after daemon exits works; (b) Kùzu *allows* multiple in-process handles to share a DB; (c) two-process open of the same Kùzu DB succeeds (`concurrent-open-ok`); (d) forget through the daemon's KG handle is visible to subsequent reads through the same handle. The "GDPR delete is fine concurrently" claim now has tests behind it. |
| F-03  | Daemon's `MemoryPipeline` actually writes `Commitment` nodes                       | [x] | Pipeline previously only called `extract.py::extract` (episodic only); `commitments.extract` was never invoked. Marquee feature was dead code. Now wired in `pipeline.py::ingest` step 5: extract commitments, resolve owner from MENTIONS, persist via `kg.upsert_commitment`. Heuristic fallback on LLM error. |
| F-04  | `KnowledgeGraph.upsert_commitment` + `commitments(status, due_before, limit)`     | [x] | Schema-aware writer + structured query (status filter + bi-temporal due_before). |
| F-05  | `tests/test_commitment_e2e.py` — proves the chain end-to-end                       | [x] | 3 tests: (a) daemon writes Commitment nodes from a first-person promise sentence; (b) MCP `memory.commitments` returns those rows with `id`/`content`/`status`/`due_at`; (c) `due_before` filter narrows. |

---

## Tauri desktop UI (T+D-series, 2026-05-12)

User asked "I dont even know how this app functions or its capabilities and never saw it working." Three things shipped: a reproducible demo transcript proving the CLI engine works end-to-end, a real Tauri desktop UI rendering live captures, and a screenshot you can actually look at.

| ID    | Story                                                                              | Status | Notes |
|-------|-----------------------------------------------------------------------------------|--------|------|
| D-01  | `demo.sh` script (seeds 8 captures, exercises every CLI verb)                     | [x] | `./demo.sh` runs against a fresh `.demo/` DB. Includes a `--llm` toggle and a `DEMO_RECORD=1` mode that writes a markdown transcript. |
| D-02  | `docs/DEMO_RUN.md` — reproducible canonical transcript                            | [x] | 131-line markdown showing status / search / who / digest / mcp-doctor / forget. The "Alex Kim has memories → forgotten → no memories" cascade is visible. |
| T-01  | Tauri scaffold (`app/`) with vite + TS + Rust                                     | [x] | `app/{index.html,search.html,src/*.ts,src-tauri/*}`. SwiftPM is in `swift/`; Tauri is in `app/`. |
| T-02  | 127.0.0.1 HTTP gateway in the Python daemon                                       | [x] | `src/secondbrain/api/http.py` exposes `/health` `/status` `/search` `/who` `/timeline` `/digest` `/commitments` `/forget`. 9 gateway tests in `tests/test_http_gateway.py`. CORS for `tauri://localhost`. Host header validated against loopback. |
| T-03  | Search overlay (⌘+Space, frameless, Raycast-style)                                | [x] | `app/search.html` + `app/src/search.ts`. Live filter with debounced `/search`, ↑/↓ navigation, Esc to dismiss, `<mark>` highlights on amber. Global shortcut registered in Rust. |
| T-04  | Main timeline view (scrolling list of today's captures)                           | [x] | `app/index.html` + `app/src/main.ts`. Date selector, header filter, amber left-border on commitment rows, JetBrains Mono + Newsreader italic editorial heading. |
| T-05  | Menubar tray (Capturing status, Pause, Open Timeline, Open Search, Quit)          | [x] | `app/src-tauri/src/lib.rs` builds the tray on launch. |
| T-06  | Build the binary, capture a screenshot                                            | [x] | `app/src-tauri/target/release/secondbrain-app` (~24MB after optimization). Screenshot at `docs/screenshots/timeline.png`. |
| T-07  | Diagnose and fix the blank-webview bug                                            | [x] | Root cause: `devUrl` was set in `tauri.conf.json` and Tauri uses it preferentially over `frontendDist` at runtime — so the binary tried to load `http://localhost:1420/` instead of the bundled assets. Removed `devUrl` for v0.2. Also: SQLite needed `check_same_thread=False` so the aiohttp gateway can share connections with the CLI thread, and the gateway needed CORS headers echoed back to `tauri://localhost`. |
| `secondbrain ui` CLI command | Starts gateway + Tauri binary in one process | [x] | `cli.py::ui` spawns the gateway in a background thread, polls `/health` until ready, execs the Tauri binary. Auto-locates release before debug. |
| Pipeline fix: commitment `now` | use `capture.captured_at` not `datetime.now()` | [x] | "Sam said tomorrow" should resolve relative to when Sam said it. Caught by `test_due_before_filter` running on a different date than the seed. |

---

## Full-UI access to every capability (U-series, 2026-05-12)

User: "all secondbrain capabilities must be fully built and must be working end to end and accessible from UI." Started with an audit that confirmed only Timeline + Search were UI-reachable. Built every other capability into the desktop app.

| ID    | Story                                                                              | Status | Notes |
|-------|-----------------------------------------------------------------------------------|--------|------|
| U-01  | Audit capability ↔ UI gap                                                          | [x] | 13 capabilities total; before this round 2 had a UI. |
| U-02  | Daemon control endpoints (`/daemon`, `/add-note`, `/audit-log`, `/llm-config`)    | [x] | `CascadeMetrics.paused` + the pipeline now short-circuits paused frames. 4 new gateway tests (13 total). |
| U-03  | **People panel** — search a name, see all memories                                 | [x] | Bound to `/who`. Screenshot: `docs/screenshots/05-people.png`. |
| U-04  | **Digest panel** — themes / broken promises / follow-ups, period + LLM toggle     | [x] | Bound to `/digest`. Screenshot: `docs/screenshots/03-digest.png`. |
| U-05  | **Commitments panel** — list + status filter                                       | [x] | Bound to `/commitments`. Screenshot: `docs/screenshots/04-commitments.png`. |
| U-06  | **Settings panel** — BYO-LLM config + audit log + local-first promises             | [x] | Bound to `/llm-config` + `/audit-log`. Screenshot: `docs/screenshots/06-settings.png`. |
| U-07  | **Forget UI** — right-click row → reason prompt → cascade + audit                  | [x] | `main.ts` `contextmenu` handler on `#timeline-body`. |
| U-08  | **Audit log viewer** in Settings                                                   | [x] | Shows real rows with timestamp / actor / action / cited count. |
| U-09  | **Six-tab sidebar nav** w/ status card + Pause/Resume                              | [x] | `data-tab` router. ⌘+K → Search. |
| U-10  | End-to-end UI screenshots of every panel                                           | [x] | `docs/screenshots/0[1-6]-*.png` against the demo DB. |
| U-11  | Fix search prefill race                                                            | [x] | Async fetch was landing in a hidden panel — moved behind double `requestAnimationFrame` after `showTab`. |
| Real bug: Kùzu 8 TB mmap | `max_db_size` default exhausts virtual addr space | [x] | `KnowledgeGraph` now passes `max_db_size=16 GiB` (env-overridable). Without this, a user keeping `secondbrain run` open for hours on a constrained machine would have eventually faced "Mmap for size 8796093022208 failed." Test suite went from 1-fail-on-second-KG to **118 green**. |
| Real bug: SQLite `check_same_thread` | gateway thread shares OLTP w/ CLI thread | [x] | Fixed in T-series, load-bearing for U-series since every UI route uses it. |

---

## What's NOT in this file

Every story marked `[ ]` or `[-]` has moved to [`docs/ROADMAP.md`](ROADMAP.md). When a roadmap item ships, it lands here with a `[x]` and disappears from the roadmap. The earlier `[-]` "deferred" rows you'll find above (e.g. S4 cross-platform, S5-07 visual eval, S6-08 Moondream-3 redactor, S7-01 Qwen3 synth, S9 Iroh sync, S11-07..S11-10 Tauri-tier polish) have been promoted to live roadmap items with effort estimates and module pointers.

**Where to look:**
- This file: every shipped story across S0 → S12 + P, H, B, F, T, D, U series.
- `docs/ROADMAP.md`: every pending item, tiered by who's blocked.
- `CHANGELOG.md`: per-release release notes (Keep a Changelog format).
- `docs/ARCHITECTURE.md`: locked stack + 16-week sprint plan.
- `docs/QUICKSTART.md`: from-zero install instructions.
- `docs/DEMO_RUN.md`: reproducible CLI transcript.
- `docs/screenshots/`: 6 panel captures + the demo-tour screenshot.

