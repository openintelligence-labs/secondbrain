# SecondBrain — The Personal Memory Substrate (v2, May 2026)

> *Open-source memory that survives your hardware vendor.*
>
> Continuously indexes screen + audio + browser + documents with **OCR-optional visual recall** (ColQwen2.5), **accessibility-tree-first capture** (<1% sustained CPU), **bi-temporal knowledge-graph memory** (Graphiti pattern on embedded Kùzu), **Reflective Memory Management** (RMM, ACL 2025) with Zettelkasten linking (A-MEM, NeurIPS 2025), federated **Iroh+Automerge** E2EE multi-device sync, and an **MCP-native** agent surface that turns any Claude/Cursor/Codex/Gemini install into a memory-augmented assistant. **GDPR-by-construction** — encrypted at rest with ChaCha20-Poly1305, per-entity cascading delete, exportable audit log, zero-network mode.
>
> No project today combines: ColQwen2.5 visual late-interaction over screenshots, AX-tree-first capture, bi-temporal KG memory with Zettelkasten linking, federated Iroh+Automerge sync, and a verifiable GDPR posture. That is exactly what SecondBrain ships.

---

## 1. Architecture

```
secondbrain/
├── src/secondbrain/
│   ├── capture/
│   │   ├── screen/
│   │   │   ├── macos_sck.py         # ScreenCaptureKit via screencapturekit-rs sidecar
│   │   │   │                         # — dirtyRects gate → IOSurface zero-copy → SCContentSharingPicker
│   │   │   ├── windows_wgc.py       # windows-capture (NiiightmareXD) — WGC primary, DXGI fallback
│   │   │   ├── linux_pw.py          # PipeWire 1.6+ via xdg-desktop-portal, RestoreToken, DMA-BUF zero-copy
│   │   │   └── dedup.py             # AX-tree-hash → dirty-rect-area → dHash → pHash verify → SSIM cascade
│   │   ├── audio/
│   │   │   ├── system.py            # SCK audio (mac) / WASAPI per-process loopback (win 2004+) / PipeWire monitor (linux)
│   │   │   ├── mic.py               # cpal-based unified mic capture
│   │   │   ├── asr.py               # whisper.cpp large-v3-turbo (Metal/Vulkan/DirectML)
│   │   │   └── diarize.py           # pyannote-community-1 (shared with MeetMind)
│   │   ├── browser/
│   │   │   ├── extension/           # SingleFile-MV3 + native-messaging host
│   │   │   ├── cdp.py               # CDP fallback: Page.captureSnapshot + Accessibility.getFullAXTree
│   │   │   ├── history.py           # Chrome/Firefox/Arc/Zen sqlite read (IMMUTABLE + WAL copy)
│   │   │   └── singlefile.py        # SingleFile snapshot on focus-lost
│   │   ├── documents/
│   │   │   ├── watcher.py           # filesystem watcher (PDF/MD/DOCX/TXT/EPUB)
│   │   │   ├── pdf.py               # PaddleOCR-VL 0.9B (default) / MinerU fallback
│   │   │   └── docx.py
│   │   ├── wearable/                # ⭐ THE OPEN INGESTION LAYER ⭐
│   │   │   ├── memorystream.py      # MemoryStream protocol spec (BLE/JSON)
│   │   │   ├── plaud_adapter.py     # Plaud Note Pro / NotePin S
│   │   │   ├── omi_adapter.py       # OMI / BasedHardware
│   │   │   ├── limitless_import.py  # one-shot import of orphaned Pendant data
│   │   │   ├── bee_import.py        # one-shot import of orphaned Bee data
│   │   │   └── rewind_import.py     # one-shot import of orphaned Rewind backups
│   │   ├── clipboard.py             # clipboard history (opt-in, redacted)
│   │   ├── ax/
│   │   │   ├── macos.py             # AXUIElement + AXEnhancedUserInterface=true (wakes Electron trees)
│   │   │   ├── windows.py           # UIA3 via uiautomation crate, CacheRequest batched reads
│   │   │   └── linux.py             # AT-SPI2 via atspi-rs
│   │   └── consent/
│   │       ├── allowdeny.py         # per-app, per-URL pattern, per-window-title regex
│   │       ├── incognito.py         # per-app pause, scheduled blackout, kill switch
│   │       ├── deny_titles.py       # window-title regex deny-list (1Password|Bitwarden|*— Banking|Teladoc|...)
│   │       └── sensitive.py         # Florence-2-base classifier → Moondream-3 redaction (two-stage)
│   ├── ocr/
│   │   ├── apple_vision.py          # macOS — RecognizeTextRequest (Vision 4, ANE, ~80–150ms)
│   │   ├── windows_ocr.py           # Windows.Media.Ocr (primary)
│   │   ├── paddleocr_vl.py          # PaddleOCR-VL 0.9B (#1 OmniDocBench v1.5 = 90.67, beats GPT-4o)
│   │   ├── rapid.py                 # RapidOCR (CPU-only fallback, 100+ langs, no GPU)
│   │   └── selector.py              # AX text first; native OS OCR; PaddleOCR-VL only if AX empty AND not visual-rich
│   ├── embed/
│   │   ├── text.py                  # Nomic Embed v2 (137M MoE, Matryoshka 64–768) — default CPU
│   │   ├── text_premium.py          # Snowflake Arctic Embed L v2.0 (568M, MRL+QAT 128 bytes/vec) — opt-in
│   │   ├── visual.py                # ColQwen2.5-v0.2 (3B) + 128-dim MaxSim projection (3% storage, 95.36% recall)
│   │   ├── visual_low.py            # ColSmol-500M for ≤8GB Macs
│   │   ├── sparse.py                # BGE-M3 sparse head
│   │   ├── audio.py                 # Whisper transcript → Nomic v2 (95% case); CLAP for non-speech
│   │   └── chunker.py               # 512 tok + 50 overlap; Jina-v3 late chunking for >2k tok inputs
│   ├── store/
│   │   ├── crypt/
│   │   │   ├── ciphers.py           # SQLite3 Multiple Ciphers (ChaCha20-Poly1305 AEAD, public domain)
│   │   │   ├── age.py               # age (X25519/ChaCha20-Poly1305) for files & snapshots
│   │   │   ├── keystore.py          # Secure Enclave / DPAPI+TPM / Secret Service+TPM2 — ADP-style key custody
│   │   │   └── jit.py               # JIT decrypt: zeroizing buffer, biometric-gated session keys
│   │   ├── timeline.py              # captures table (DuckDB-backed for analytics; SQLite-WAL for OLTP)
│   │   ├── vector.py                # LanceDB (multi-vector ColPali native); sqlite-vec dev fallback <100k
│   │   ├── kg.py                    # ⭐ Kùzu (embedded Cypher-compatible graph DB) — bi-temporal edges
│   │   ├── tantivy.py               # tantivy BM25 (Rust, ~2× Lucene, embedded)
│   │   └── retention.py             # tiered TTL: 7d raw HEVC, 90d OCR + ColPali patches, ∞ embeddings + facts
│   ├── search/
│   │   ├── hybrid.py                # tantivy BM25 ⊕ LanceDB dense → RRF k=60 → mxbai-rerank-base-v2
│   │   ├── visual.py                # ColQwen2.5 query → MaxSim over multi-vector
│   │   ├── temporal.py              # bi-temporal KG queries: "before X event" / "around date Y" / validity intervals
│   │   ├── rerank.py                # mxbai-rerank-base-v2 (CPU); auto-upgrade to jina-reranker-v3 if Metal/CUDA
│   │   ├── tune.py                  # ⭐ "personalize my retrieval" wizard — 50 thumbs-up/down → tuned α
│   │   └── context.py               # rerank-then-stuff (N=50 → K=5, 10:1 compression)
│   ├── memory/
│   │   ├── extract.py               # event → typed pydantic memory (MaRS schema: episodic/semantic/procedural/commitment)
│   │   ├── amem.py                  # ⭐ A-MEM Zettelkasten linking (NeurIPS 2025) — retroactive note rewriting
│   │   ├── rmm.py                   # ⭐ Reflective Memory Management (ACL 2025) — prospective+retrospective + RL rerank
│   │   ├── entities.py              # cross-app entity resolution (face → calendar → email → Slack handle → voiceprint)
│   │   ├── commitments.py           # typed commitment nodes (due_at, status); broken-promise sweep
│   │   ├── importance.py            # Gemma 3 4B-IT scorer (cheap, every event)
│   │   ├── reflect.py               # Qwen3-8B Q4_K_M synthesizer (daily/weekly/monthly digest, thinking mode)
│   │   ├── forget.py                # FadeMem dual half-life (long ~11.25d / short ~5.02d) gated by importance
│   │   └── digest.py                # daily 07:30 / weekly Sun 09:00 / monthly retro
│   ├── sync/
│   │   ├── iroh.py                  # ⭐ Iroh QUIC + dial-by-pubkey, near-100% NAT traversal
│   │   ├── automerge.py             # CRDT for facts, tags, KG edges (last-writer-wins is wrong here)
│   │   ├── blobs.py                 # iroh-blobs ≥1.0 for embedding shards (gated; Syncthing fallback v0)
│   │   ├── peer.py                  # device pairing via QR + age recovery phrase
│   │   └── policy.py                # what to sync per device class (phone↔laptop≠tablet)
│   ├── share/
│   │   ├── moment.py                # extract a 30s clip
│   │   ├── redact.py                # Moondream-3 face/PII/password redaction
│   │   └── export.py                # signed shareable URL with expiration
│   ├── compliance/
│   │   ├── audit.py                 # exportable audit log of every retrieval (GDPR Art. 30 ready)
│   │   ├── erasure.py               # right-to-be-forgotten cascade — by entity, source app, time window
│   │   ├── dpia.py                  # `secondbrain compliance report` → human-readable DPIA
│   │   └── air_gap.py               # zero-network mode (binary-verifiable)
│   ├── api/
│   │   ├── http.py                  # FastAPI 127.0.0.1; Origin validation (DNS rebinding defense)
│   │   ├── mcp_server.py            # ⭐ MCP Streamable HTTP + OAuth 2.1 PKCE — 7 named tools
│   │   └── sse.py                   # streaming search results
│   ├── ui/
│   │   ├── tray.py                  # menubar with one-tap kill switch
│   │   ├── timeline.tsx             # Tauri scrubber UX (Rewind-killer feature)
│   │   ├── search.tsx               # ⌘-Space global search
│   │   ├── digest.tsx               # one-glance "yesterday → today" card
│   │   └── consent.tsx              # explicit retention TTL + allow/deny + air-gap toggles
│   ├── eval/                        # ⭐ public, scriptable benchmark suite
│   │   ├── longmemeval.py           # primary (ICLR 2025) — target ≥90
│   │   ├── locomo.py                # secondary (Snap)         — target ≥91
│   │   ├── perltqa.py               # personal-profile probe
│   │   └── replay.py                # weekly CI: 200 hand-curated queries with ground truth
│   ├── cli.py
│   └── daemon.py                    # background capture service
```

---

## 2. The capture cascade — the locked algorithm

```
Frame opportunity (event-driven preferred over polling: app switch / AX focus change / click / scroll-stop / 1Hz heartbeat)
   │
   ▼
Window-title deny-list match? ──── yes ──→ skip (0 ms — kills 80% of "Recall got crucified for this" frames before VLM)
   │ no
   ▼
AX-tree SHA-256 of focused subtree unchanged? ── yes ──→ skip (zero cost; <1 ms)
   │ no
   ▼
AX-tree text available?  ──── yes ──→ persist text + URL + app + window-title
   │ no                                (no screenshot, no OCR — battery WIN)
   │                                   (Electron: AXEnhancedUserInterface=true forces tree)
   │
   ▼
Dirty-rect area < 0.5% of display? ── yes ──→ skip (SCK + WGC native; near-zero idle cost)
   │ no
   ▼
dHash 8×8 (0.33 ms): Hamming ≤ 4 vs last frame? ── yes ──→ skip
   │ no                                        (≤10 borderline → pHash verify ~2 ms)
   ▼
SSIM > 0.96 on 256×256 thumbnail of dirty region? ── yes ──→ skip
   │ no
   ▼
Florence-2-base sensitive-content classifier (~80 ms binary)
   ──── yes ──→ Moondream-3 redaction-mask generation; persist redacted thumbnail + AX redacted text
   │ no
   ▼
Persist:
  - frame.heic (HEVC via VideoToolbox / Media Foundation / NVENC — never libx265)
  - AX text (already extracted)
  - OS-native OCR (Apple Vision / Win.Media.Ocr) only if AX empty
  - PaddleOCR-VL 0.9B fallback only if native OCR confidence < 0.7 AND content is dense
  - ColQwen2.5 multi-vector patches (always — bypasses OCR for visual queries)
  - Nomic v2 embedding of AX/OCR text (Matryoshka 768→128 for hot index)
  - context: app, URL, window title, focused element, timestamp, monitor index
  - emit episode → memory pipeline (extract → A-MEM link → KG edge)
```

**Result**: <1% sustained CPU on most apps (because AX usually wins, no pixel work), pixel storage for ~5% of frames (visual-rich content), full searchability via four modalities (text BM25, dense semantic, ColQwen visual, KG temporal). p99 frame budget < 100 ms.

This is the single most important architectural decision. It directly attacks Rewind's #1 churn driver (battery / thermal) and Recall's #1 trust gap (always-on indiscriminate pixel capture).

---

## 3. Stack decisions (locked May 2026)

### 3.1 Capture
| Layer | macOS | Windows | Linux |
|---|---|---|---|
| Screen | **ScreenCaptureKit** (screencapturekit-rs) — IOSurface zero-copy, dirtyRects gate, SCContentSharingPicker, HDR opt-in | **windows-capture** 1.5+ (WGC primary, DXGI fallback) — Win11 26H2 HDR-correct | **PipeWire 1.6+** via xdg-desktop-portal ScreenCast, RestoreToken persisted, DMA-BUF zero-copy |
| AX | AXUIElement + `AXEnhancedUserInterface=true` (wakes Electron trees) | UIA3 (`uiautomation` crate), CacheRequest batched COM | AT-SPI2 (`atspi-rs`) |
| Audio (sys) | SCK audio tap (single-API parity) | WASAPI per-process loopback (Win10 2004+) | PipeWire monitor sources |
| Mic | cpal | cpal | cpal |

### 3.2 Vision / OCR / Embeddings
| Layer | Choice | Why |
|---|---|---|
| OCR (mac) | **Apple Vision RecognizeTextRequest** (Vision 4, macOS 26 Tahoe, ANE) | Free, system-level, ~80–150 ms |
| OCR (win) | **Windows.Media.Ocr** primary | Native, free |
| OCR fallback (heavy docs / non-Latin) | **PaddleOCR-VL 0.9B** | #1 OmniDocBench v1.5 = 90.67, beats GPT-4o, 40% less VRAM than dots.ocr, Apache-2.0 — **competitor moat** |
| OCR fallback (low-RAM CPU) | **RapidOCR** (PP-OCRv5 ONNX) | 100+ langs, no GPU |
| Sensitive classifier | **Florence-2-base** (~80 ms binary) → **Moondream-3** redaction (only on positives) | Two-stage keeps p99 < 100 ms |
| Visual embeddings | **ColQwen2.5-v0.2 (3B) + 128-dim MaxSim projection** | 3% storage, 95.36% recall — **the moat** |
| Visual embeddings (low VRAM) | ColSmol-500M | Runs on 8GB Macs |
| Text embeddings (default) | **Nomic Embed v2** (137M MoE, Matryoshka, Apache-2.0) | CPU-friendly, multilingual |
| Text embeddings (premium) | **Snowflake Arctic Embed L v2.0** (568M, MRL+QAT 128 bytes/vec) | 10× more history at same disk cost |
| Sparse | **BGE-M3 sparse head** | One model = dense + sparse + multivec |
| Late chunking | **Jina v3 late chunking** for inputs >2k tok | Free quality on long transcripts |
| Reranker (CPU) | **mxbai-rerank-base-v2** (0.5B) | 55.57 BEIR, <100 ms on M-series |
| Reranker (GPU) | **mxbai-rerank-large-v2** (1.5B) | 57.49 BEIR (was jina-reranker-v3 in an earlier draft; swapped due to its CC-BY-NC license) |
| Audio embeddings | Whisper-large-v3-turbo transcript → Nomic v2 (95% case) | 5% case: CLAP for non-speech |

### 3.3 Storage / Crypto / Sync
| Layer | Choice | Why |
|---|---|---|
| Vector store | **LanceDB** (embedded, columnar, native multi-vector ColPali) | Only embedded store with ColPali support + 10M+ vector ceiling |
| Graph store | **Kùzu** (embedded, columnar, Cypher-compatible) | Bi-temporal KG without Neo4j daemon |
| BM25 | **tantivy** (Rust, ~2× Lucene, embedded) | Beats SQLite FTS5; Turso replaced FTS5 with tantivy |
| OLTP | SQLite-WAL via **SQLite3 Multiple Ciphers** (ChaCha20-Poly1305 AEAD, public domain) | Faster than SQLCipher AES-CBC on Apple Silicon / Snapdragon X |
| File encryption | **age** (X25519 + ChaCha20-Poly1305) | Modern, no GPG keyring nightmare |
| Key custody | **Secure Enclave (mac) / DPAPI+TPM (win) / Secret Service+TPM2 (linux)** + per-record DEKs wrapped by device root key | Apple ADP architecture replicated on every OS |
| JIT decrypt | Biometric-gated session keys, zeroizing buffer | "We literally cannot read your data" — Rewind couldn't claim this |
| Hybrid retrieval | **RRF k=60** zero-config + tunable convex combination + cross-encoder rerank | Bullet-proof default; tuned beats RRF when α tuned with ~50 labeled pairs |
| Sync v0 | Syncthing 2.x (encrypted SQLite + age-blob folder) | Stopgap until Iroh stack lands |
| Sync v0.3+ | **Iroh** (QUIC, dial-by-pubkey, ~100% NAT traversal) + **Automerge** (CRDT for facts) + **iroh-blobs ≥1.0** for shards | Zero-server federation, no relay-of-trust |
| Frame codec | HEVC via VideoToolbox / Media Foundation / NVENC | Never bundle libx265 (patent risk); HW-licensed paths only. AV1 gated to M3+/RTX 40+ |

### 3.4 Memory / Reflection / Agents
| Layer | Choice | Why |
|---|---|---|
| Memory algorithm | **A-MEM Zettelkasten** (NeurIPS 2025) + **RMM** (ACL 2025) | Self-organizing notes + prospective/retrospective reflection with RL rerank — **moat combo** |
| Memory schema | MaRS-typed pydantic: episodic / semantic / procedural / **commitment** | Commitment as first-class node-type — nobody else ships this |
| KG temporality | **bi-temporal** (event-time + ingestion-time) Graphiti pattern on Kùzu | 18.5% LongMemEval lift over flat vector RAG; 70× context reduction |
| Reflection model (synth) | **Qwen3-8B Q4_K_M** (Apache-2.0, dual-mode) | Thinking mode for nightly synthesis |
| Reflection model (score) | **Phi-4-mini (3.8B, MIT)** primary; Gemma 3 4B-IT optional | Phi-4-mini is OSI-clean MIT (Gemma uses a custom permissive license). |

### 3.5 S0 spike-validated baseline (May 2026)

The first PR (`spikes/`) validated all stack assumptions on a real Apple Silicon Mac (Python 3.13, torch 2.10, MPS):

| Component | Spike result |
|---|---|
| **Kùzu 0.11.3** bi-temporal graph | p50 0.41 ms / p95 7.3 ms `as_of` query on 1050 nodes |
| **LanceDB 0.30.2** multi-vector | 100 docs × ~24 patches × 128-d inserted in 6.7 ms; MaxSim ranked correctly |
| **ColQwen2.5-v0.2** on MPS | 16.3 s warm to encode 5 screenshots (≈3.3 s/image); MaxSim 235 ms across 5 docs. **Note: original arch claim of `<5s for 5 images` was per-amortized; actual single-shot is ~3 s/image, set realistic SLO.** |
| **Nomic Embed v2 MoE** on CPU | 83.7 strings/sec on a laptop (4× the 20/sec MVP bar) |
| **Encrypted SQLite** | AES-256 round-trip + macOS Keychain custody + wrong-key rejection + on-disk header is non-plaintext |
| **tantivy 0.26.0** BM25 | 1000 docs indexed in 366 ms, BM25 query 0.18 ms, RRF k=60 fusion shape verified |

**Cipher swap deferred:** `sqlcipher3-wheels` (AES-256 SQLCipher) ships a Python 3.13 wheel today; **SQLite3 Multiple Ciphers** (ChaCha20-Poly1305) does not yet. Python API surface is identical, so the swap is a C-layer change when the wheel lands. Acceptance: SQLite3 Multiple Ciphers is the locked target; AES-256 SQLCipher is the v0.x interim.
| Reflection trigger | Hybrid: token-threshold (60% ctx) + idle-window (>5 min) + cron (07:30 / Sun 09:00 / monthly) | Mastra + Limitless pattern |
| Forgetting | FadeMem dual half-life (~11.25d long / ~5.02d short) gated by importance + per-entity cascading delete | GDPR Art. 17 as a feature |
| MCP transport | **Streamable HTTP** (POST + GET-upgraded SSE, `Mcp-Session-Id`) + stdio | Spec 2025-11; SSE-only deprecated |
| MCP auth | OAuth 2.1 PKCE (resource server pattern) | Spec-compliant; works in all clients |
| Eval | **LongMemEval** ≥90 / **LoCoMo** ≥91 / **PerLTQA** + private 200-query replay harness in CI | Public + private; auto-publish in README |

---

## 4. Data model

```python
class Capture(BaseModel):
    id: ULID
    source: Literal["screen", "audio", "browser", "document", "clipboard", "wearable"]
    captured_at: datetime
    app_name: str | None
    window_title: str | None
    url: str | None
    file_path: Path | None
    ax_text: str | None                 # accessibility tree text (preferred path)
    ocr_text: str | None                # only if ax_text is None
    text_hash: bytes
    pixel_hash: bytes | None            # dHash, only if frame stored
    pixel_path: Path | None             # encrypted HEVC frame (age)
    sensitive: bool = False
    redacted: bool = False
    monitor_index: int | None
    capability_cache_hit: bool          # did AX cache hit? (avoids re-probe)

class MemoryNode(BaseModel):
    """MaRS-typed memory primitive."""
    id: ULID
    type: Literal["episodic", "semantic", "procedural", "commitment"]
    content: str
    embedding: bytes                    # Nomic v2 768-dim float32 (Matryoshka 128 for hot index)
    importance: float                   # 0–10, Gemma-3 scored
    valid_from: datetime                # bi-temporal: event time
    valid_to: datetime | None           # bi-temporal: when fact stopped being true
    ingested_at: datetime               # bi-temporal: when we learned it
    superseded_by: ULID | None          # KG-style fact succession
    sources: list[ULID]                 # provenance → Capture.id (cascading delete)
    tags: list[str]
    linked_to: list[ULID]               # A-MEM Zettelkasten links (bidirectional)
    decay_factor: float                 # FadeMem half-life modifier

class Commitment(MemoryNode):
    """First-class commitment node — nobody else ships this typed."""
    type: Literal["commitment"] = "commitment"
    owner: ULID                         # FK → Person.id
    promised_to: ULID | None            # FK → Person.id
    due_at: datetime | None
    status: Literal["open", "in_progress", "done", "cancelled", "broken"]
    closed_in: ULID | None              # which capture/event closed it

class Person(BaseModel):
    id: ULID
    name: str
    aliases: list[str]                  # email, handles, calendar names
    voiceprint: bytes | None            # 192-dim ECAPA (shared with MeetMind)
    face_embedding: bytes | None        # for cross-app entity resolution
    last_interaction: datetime
    interaction_count: int

class Reflection(BaseModel):
    id: ULID
    period: Literal["day", "week", "month", "year"]
    period_start: date
    themes: list[str]
    broken_promises: list[ULID]         # → Commitment.id (status='broken')
    suggested_followups: list[str]
    importance_sum: float
    cited_evidence: list[ULID]          # RMM: every claim cites Capture.id
```

---

## 5. The reflection loop — A-MEM × RMM (the "second mind" feature)

```
Continuous (per event):
  importance_score = Gemma-3-4B(event) ∈ [0, 10]   # cheap; runs on every event
  if importance_score > 3:
    extract → MemoryNode(type, content, embedding, valid_from, sources, tags)
    A-MEM:
      neighbors = KG.find_similar(node, k=5)
      for n in neighbors:
        Qwen3-8B.rewrite(n)  ← retroactive note rewriting (NeurIPS 2025)
      KG.add_links(node ↔ neighbors)

Reflection trigger (token-threshold OR idle OR cron):
  RMM-prospective:
    sessions = KG.unreflected(period)
    summary = Qwen3-8B(thinking).synthesize(sessions)  # cited evidence required
    KG.add(summary, sources=[s.id for s in sessions])
  
  RMM-retrospective:
    last_24h_queries = audit.recent()
    rerank_reward = +1 for cited results, -1 for ignored
    update online RL reranker

Daily 07:30 digest:
  themes = top-K cluster centroids of yesterday's nodes
  broken_promises = Commitment.filter(due_at < now, status='open')
                         .where(owner == self)  # broken-promise sweep
  tomorrow_plan = Qwen3-8B.plan(yesterday_loose_ends + open_commitments)
  surface in morning UI; optional MCP push to Slack/Notion/Obsidian
```

**Why this beats everyone**: Mem0 / Letta / MemMachine each ship one of these (extraction, OS-tier memory, ground-truth preservation). Zep ships bi-temporal KG. **Nobody ships A-MEM + RMM + bi-temporal KG + typed commitments together.** This is what gets us to the credible cluster on LongMemEval (target ≥90).

---

## 6. Federated multi-device sync

**Phase 1 (v0.x):** Syncthing 2.x for the encrypted SQLite + age-blob folder. Works today; unblocks dogfooding.

**Phase 2 (v0.5+):** Migrate to **Iroh + Automerge**:
- Iroh QUIC dial-by-public-key, ~100% NAT traversal, no central server.
- Automerge CRDTs for facts, tags, KG edges (last-writer-wins is wrong for tag edits).
- iroh-blobs ≥1.0 for embedding shards (gated; wait for blob storage to stabilize).
- Pair via QR-displayed device fingerprint + 24-word age recovery phrase.

```
Phone (audio capture) ←→ Laptop (screen capture) ←→ Tablet (reading capture)
                              │
                       all queryable from each device
                              │
                       no central server, no FAANG involved, no relay-of-trust
```

Sync **only** summaries, embeddings, and structured facts across devices — never raw frames or audio.

---

## 7. MCP-native agent surface — 7 locked tools

Streamable HTTP transport, OAuth 2.1 PKCE, lowercase dot-namespaced names. Same server config works in Claude Desktop, Cursor, Windsurf, Codex, Gemini CLI.

```
1. memory.search(query, time_range?, person?, source?)
2. memory.recall_timeline(start, end, granularity)
3. memory.get_person(name|id)              # entity card with face/voice/last interaction
4. memory.commitments(status, due_before)  # ⭐ first-class commitment surface
5. memory.daily_digest(date)
6. memory.add_note(text, tags)             # explicit user write
7. memory.forget(entity_id|time_range, reason)  # ⭐ GDPR primitive as first-class tool
```

**The flywheel**: install SecondBrain → install Claude Desktop / Cursor / Codex → instantly your assistant has memory of your life. **Users will install SecondBrain just to give Claude memory.**

---

## 8. Privacy + compliance — GDPR-by-construction

- **Storage**: SQLite3 Multiple Ciphers (ChaCha20-Poly1305 AEAD) + age files. Per-record DEKs wrapped by device root key in Secure Enclave / TPM.
- **Just-in-time decrypt**: keys derived only after biometric unlock (Touch ID / Windows Hello / fingerprint). Apple-ADP architecture, replicated cross-platform.
- **Sensitive-content filter**: Florence-2-base classifier (~80ms) → Moondream-3 redaction at capture. Ahead of Pieces.
- **Window-title deny-list**: 1Password|Bitwarden|*— Banking|Teladoc|… caught at 0ms before any VLM. Kills 80% of "Recall got crucified" frame classes upfront.
- **Allow/deny**: per-app, per-URL pattern, per-window-title regex. System-wide.
- **Incognito zones**: per-app pause (right-click → "stop SecondBrain"), scheduled blackout (9pm–7am), one-tap menubar kill switch.
- **Retention tiers (user-visible)**: 7 days raw HEVC frames, 90 days OCR + ColPali patches, ∞ embeddings + structured facts. All user-configurable in the UI.
- **Right to delete (GDPR Art. 17)**: `secondbrain forget --person "Sam"` cascades to all captures, embeddings, voiceprints, audio, KG edges. **Exposed as MCP tool `memory.forget`.**
- **Audit log (GDPR Art. 30)**: every retrieval logged locally. `secondbrain compliance audit` exports.
- **DPIA report**: `secondbrain compliance report` → human-readable "what we store about whom, where, for how long."
- **Air-gap mode**: `secondbrain --offline` is binary-verifiable (no syscall to any non-localhost endpoint). For regulated environments.
- **Network**: HTTP API binds 127.0.0.1 only with Origin validation (DNS-rebinding defense). No outbound except (a) configured LLM (default Ollama localhost) and (b) explicit Iroh sync mesh.

**EU AI Act**: fully applicable Aug 2, 2026. SecondBrain is designed so a regulated environment (hospital, legal, finance) can deploy it post-enforcement: encrypted at rest, auditable, air-gappable, right-to-erasure as a first-class primitive.

---

## 9. The 7 moonshot differentiators (locked)

1. **OCR-Optional Visual Recall via ColQwen2.5-v0.2 (3B) + 128-dim MaxSim.** Visual late-interaction embeddings as the *primary* index for pixel content. "Find the slide with the red Q3 chart" works without any OCR ever firing.

2. **Accessibility-Tree-First Capture with per-app capability cache.** AX-only on apps that expose it (Electron via `AXEnhancedUserInterface=true`, Chromium UIA, native), with screenshot as fallback only. Per-app cache so we don't re-probe each session. <1% sustained CPU — screen-history tools historically churn users on battery/thermal cost, and this design removes that cost class.

3. **Bi-Temporal Knowledge Graph + A-MEM + RMM.** Three SOTA papers in one stack. Bi-temporal validity intervals on every edge (Graphiti pattern, 18.5% LongMemEval lift). A-MEM Zettelkasten retroactive note-rewriting (NeurIPS 2025). RMM prospective/retrospective reflection with cited-evidence RL reranker (ACL 2025). Plus typed `commitment` nodes as a first-class memory primitive.

4. **Federated E2EE via Iroh + Automerge.** No central server, no relay-of-trust. Phone audio + laptop screen + tablet reads → one query searches all three.

5. **MCP-Native Agent Surface with `memory.forget` as a first-class tool.** Out-of-the-box MCP server. Claude/Cursor/Codex/Windsurf/Gemini instantly get memory. SecondBrain becomes the *substrate* other AI apps build on, and deletion is a first-class tool rather than a buried setting.

6. **GDPR-by-Construction.** Encrypted at rest (ChaCha20-Poly1305), JIT decrypt, per-entity cascading delete, exportable audit log, binary-verifiable air-gap mode. Designed to be deployable in regulated environments after EU AI Act enforcement (Aug 2, 2026).

7. **Open Ingestion Layer for Orphaned Wearables.** Documented MemoryStream protocol (BLE/JSON) + adapters for Plaud Note Pro/NotePin S, OMI, and one-shot importers for discontinued devices (Limitless Pendant, Bee, Rewind backups). **"Your memories outlive any company."**

---

## 10. Roadmap to v1.0 (16 weeks)

| Milestone | Weeks | Deliverable |
|---|---|---|
| v0.1 | 1–2 | macOS ScreenCaptureKit + AX-first capture cascade + window-title deny-list |
| v0.2 | 3 | Apple Vision OCR + Nomic v2 + LanceDB + tantivy + RRF k=60 hybrid search |
| v0.3 | 4 | Kùzu KG + MaRS schema + cross-app entity resolution + bi-temporal edges |
| v0.4 | 5–6 | Windows + Linux capture parity (windows-capture / PipeWire RestoreToken) |
| v0.5 | 7 | **ColQwen2.5-v0.2 visual embeddings + MaxSim search** (the moat) |
| v0.6 | 8 | SQLite3 Multiple Ciphers + age + Secure Enclave/TPM + Florence-2/Moondream-3 sensitive filter |
| v0.7 | 9–10 | A-MEM + RMM reflection + Qwen3-8B / Gemma 3 4B + commitment tracking + daily digest |
| v0.8 | 11 | MCP server (Streamable HTTP + OAuth 2.1) + 7 tools + 5 first integrations |
| v0.9 | 12–13 | Iroh + Automerge sync (Syncthing fallback retained) |
| v0.95 | 14 | Browser extension (SingleFile-MV3 + CDP AX-tree) + MeetMind audio merge |
| v0.99 | 15 | Wearable adapters (Plaud, OMI, Limitless import, Bee import, Rewind import) + Tauri polish |
| **v1.0** | 16 | LongMemEval ≥90 / LoCoMo ≥91 published / `secondbrain-eval` open-sourced / public launch |

---

## 11. Risk register

| Risk | Mitigation |
|---|---|
| LanceDB Lance format young (~3 yrs) | Periodic Parquet exports; SQLite shadow table for OLTP |
| Iroh + iroh-blobs pre-1.0 risk | Feature flag; Syncthing 2.x fallback retained through v0.9 |
| Kùzu maturity vs Neo4j | SQLite-graph-shim fallback compiled-in |
| MCP spec moving | Pin to 2025-11; CI smoke test against Claude Desktop / Cursor / Codex weekly |
| Local LLM reflection cost | Tier it — Gemma 3 4B for scoring, Qwen3 8B only daily/weekly |
| HEVC patents (commercial use) | Hardware-licensed paths only (VideoToolbox / MF / NVENC); never bundle libx265 |
| LongMemEval saturating | Track LongMemEval-v2 / "Recall to Forgetting" (arxiv 2604.20006) as it lands |
| Capture privacy bug → trust backlash | Two-stage VLM redaction + window-title deny-list + binary-verifiable air-gap mode |

---

## 12. Definition of done for v1.0

1. macOS + Windows + Linux capture parity, all event-driven, all <1% sustained CPU.
2. Visual + text + audio + KG retrieval from a single `secondbrain search` call, P95 <300ms.
3. Daily reflection card with cited evidence + broken-promise sweep.
4. MCP server connecting to Claude Desktop, Cursor, Codex, Windsurf, Gemini in one click each.
5. `memory.forget --person "Sam"` cascades to every modality and every device.
6. `secondbrain compliance report` produces a human-readable DPIA.
7. Iroh + Automerge sync between two laptops + one phone, offline-tolerant.
8. Plaud + OMI adapters working end-to-end. Limitless / Bee / Rewind one-shot importers tested with real orphaned exports.
9. LongMemEval ≥90 / LoCoMo ≥91 published with reproducible script.
10. Public launch ready.
