# Changelog

All notable changes to SecondBrain are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.2] - 2026-07-30

### Fixed
- Notes added via `memory.add_note` (MCP tool or the gateway's `/add-note`) are now
  indexed into LanceDB + tantivy through the same capture → chunk → embed → index
  path the daemon uses, so `/search` hybrid retrieval finds them. Notes get an OLTP
  capture row, a KG `Capture` node with `DERIVED_FROM` provenance (so
  `memory.forget --capture-id` cascades), and an audit entry. When the embedder is
  unavailable, notes degrade to BM25-only indexing and the next `secondbrain index`
  bulk pass backfills the vector side. Closes
  [#7](https://github.com/openintelligence-labs/secondbrain/issues/7).
- The actants (Ollama) embedding backend no longer crashes when its sync surface
  (`TextEmbedder.embed_passages` / `embed_query`) is called from a running event
  loop — e.g. the gateway's async handlers or the daemon's consume loop. Found by
  the live end-to-end check for #7; embedding now bridges to a private thread's
  loop instead of calling `asyncio.run` on a busy thread.

## [0.3.1] - 2026-07-29

### Changed
- Published to PyPI as **`secondbrain-ai`** (the name `secondbrain` on PyPI belongs to an
  unrelated package). Install with `pip install secondbrain-ai`; the CLI command and
  import name remain `secondbrain`.
- Default LLM test model is now local (`gemma4:latest`) so the suite never egresses;
  daemon gained a configurable `llm_timeout_s`.
- Pinned `mcp<2` (mcp 2.0 removed `mcp.server.fastmcp`).

## [0.3.0] - 2026-07-29

### Added
- Sensitive-content redaction gate wired into the dedup cascade (heuristic
  baseline; the Florence-backed model lands behind a `[redact]` extra later).
- `--redact` / `--redact-threshold` flags on `secondbrain run-synthetic` so the
  gate can be smoke-tested without a display.
- Redaction events are now recorded in the signed audit log, keeping the
  compliance trail complete when frames are dropped before persistence.
- `[ml]` and `[visual]` optional-dependency extras so the heavy ML stacks
  (sentence-transformers/torch, ColQwen2.5) are opt-in instead of mandatory.
- `mcp` and macOS PyObjC frameworks moved into base dependencies so a clean
  `pip install secondbrain` works on a fresh Mac.

### Fixed
- Test-order pollution: a daemon started with `enable_llm=True` leaked its
  LLM-backed commitment/importance/digest extractors into every later test
  (broke `/commitments` gateway tests whenever Ollama was reachable). Globals
  are now reset around each test via a shared conftest fixture.
- Two CI-runner-only test failures and all ruff lint/format errors.

## [0.2.0] - 2026-05-16

### Added
- Capture daemon: ScreenCaptureKit Swift sidecar, AX-tree walker, and the
  cheapest-first dedup cascade (deny-list → AX-hash → dirty-rect → dHash →
  pHash → SSIM → persist).
- Storage: encrypted SQLite (SQLCipher) OLTP, LanceDB vectors, tantivy BM25,
  and a Kùzu knowledge graph.
- Hybrid retrieval (BM25 ⊕ dense → RRF), KG-aware filtering, and an optional
  mxbai reranker.
- Memory layer: extractor, A-MEM linker, entity resolver, importance scorer,
  commitment tracking, decay, and daily/weekly/monthly digests.
- MCP surface: FastMCP stdio server with 7 named tools (including
  `memory.forget` for GDPR Art. 17 cascading deletes) plus an HTTP gateway
  and Tauri desktop UI.
- BYO-LLM contract via actants (`SECONDBRAIN_LLM_*` env vars); local Ollama
  by default, six providers supported. Heuristic baselines on every LLM hot
  path so a flaky provider never blocks ingestion.
- Wearable importers (MemoryStream v1 + Plaud/OMI/Limitless/Bee/Rewind),
  sync policy + X25519 pairing, compliance audit log, and air-gap mode.

## [0.1.0] - 2026-04-26

### Added
- Initial public release (tagged `v0.0.1`): project scaffold, chunking core,
  and the first capture/index prototype.

[0.3.0]: https://github.com/openintelligence-labs/secondbrain/compare/856ad01...v0.3.0
[0.2.0]: https://github.com/openintelligence-labs/secondbrain/compare/v0.0.1...856ad01
[0.1.0]: https://github.com/openintelligence-labs/secondbrain/releases/tag/v0.0.1
