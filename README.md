<div align="center">

# SecondBrain

**Your personal AI memory. On your device. On your terms.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.3.2-informational.svg)](https://github.com/openintelligence-labs/secondbrain/releases)
[![CI](https://github.com/openintelligence-labs/secondbrain/actions/workflows/ci.yml/badge.svg)](https://github.com/openintelligence-labs/secondbrain/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org)
[![Powered by actants](https://img.shields.io/badge/powered%20by-actants-7c3aed.svg)](https://github.com/openintelligence-labs/actants)
[![MCP](https://img.shields.io/badge/MCP-native-111111.svg)](https://modelcontextprotocol.io)

**An open-source, local-first personal memory daemon.**
Captures, embeddings, knowledge graph, and audit log never leave your device.

[Quick start](#quick-start) · [How it works](#how-it-works) · [Why](#why-this-exists) · [⭐ Star us on GitHub](https://github.com/openintelligence-labs/secondbrain)

</div>

---

## Why this exists

Modern knowledge work generates more context than any human can hold — meetings, threads, docs, browser tabs, code windows. The tools that promise to help typically lock your memory inside a vendor or stream your screen to someone else's GPU.

**SecondBrain is a personal memory daemon that runs entirely on your Mac.** It captures your screen, indexes it across four storage layers, and exposes that memory to any MCP-aware assistant — Claude Desktop, Cursor, Codex — through seven first-class tools. The default LLM is local Ollama; if you opt into a hosted provider, only the prompt text leaves your machine, and only because you said so.

## Quick start

> **macOS 14+ (Apple Silicon).** Windows/Linux paths raise `NotImplementedError` today.

```bash
git clone https://github.com/openintelligence-labs/secondbrain && cd secondbrain
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,ml]'
.venv/bin/secondbrain run --fps 1                 # start the capture daemon
```

The `[ml]` extra installs the local text embedder (sentence-transformers + PyTorch). Skip it if you plan to use Ollama-served embeddings or the `--stub-embedder` flag — local embeddings pull ~2 GB of model weights on first use. For visual recall via ColQwen2.5 add `[visual]`; for BYO hosted LLMs add `[byo-llm]`.

For the full desktop app (Tauri shell + Swift sidecars), build the two extra components after the Python install:

```bash
( cd swift/SecondBrainCapture && swift build -c release )
( cd app && npm install && npm run build && cd src-tauri && cargo build --release )
.venv/bin/secondbrain ui                          # launches the desktop window
```

Want to drive it without granting macOS Screen Recording first? Run `./demo.sh` for a seeded fixture workday.

## Features

| | What it does |
|---|---|
| **Continuous capture** | ScreenCaptureKit sidecar at 1 fps, AX-tree-first dedup cascade (deny-list → AX-hash → dirty-rect → dHash → pHash → SSIM), <1ms median per gate. |
| **Hybrid retrieval** | Tantivy BM25 ⊕ LanceDB cosine → RRF k=60 → mxbai-rerank. p95 of 35 ms over 500 captures. |
| **Visual recall** | ColQwen2.5 late-interaction embeddings let you search for what a screen *looked like*, not just what it said. |
| **Bi-temporal knowledge graph** | Kùzu KG tracks valid-time and transaction-time for every entity. "What did I know about X last Tuesday?" is a first-class query. |
| **MCP-native** | A FastMCP server exposes 7 tools — `memory.search`, `memory.who`, `memory.digest`, `memory.forget`, and more — over stdio or Streamable HTTP. |
| **BYO-LLM** | Default is local Ollama. Switch to OpenAI, Anthropic, Gemini, Groq, or Mistral with three environment variables. Every LLM hot path has a deterministic heuristic fallback. |
| **GDPR by construction** | SQLCipher AES-256 at rest, age-encrypted files, biometric-gated session keys, signed audit log, and `memory.forget` as a first-class cascading delete. |

## How it works

```text
  screen ──▶ cascade ──▶ extract ──▶ ┬─▶ SQLite  (OLTP, SQLCipher)
  (SCK)     (dedup 6   (entities,    ├─▶ LanceDB (dense vectors)
            stages)    importance)   ├─▶ tantivy (BM25)
                                     └─▶ Kùzu    (bi-temporal KG)
                                           │
                               ┌───────────┴────────────┐
                               ▼                        ▼
                        hybrid retrieval         Tauri desktop
                        (RRF k=60 + rerank)      + MCP server (7 tools)
```

Everything above the retrieval line stays on disk, encrypted. The MCP server and desktop app sit on top of the same retrieval layer, so a query from Claude Desktop and a click in the timeline window run the identical pipeline.

### CLI surface

| Command | Purpose |
|---|---|
| `secondbrain run` | Start the capture daemon. `--fps`, `--ocr-fallback`, `--llm`, `--visual` flags. |
| `secondbrain run-synthetic` | Same pipeline, synthetic frames — no display or TCC required. |
| `secondbrain index` | Bulk re-index OLTP → KG / Lance / tantivy. |
| `secondbrain search "<query>"` | Hybrid search with optional `--rerank`. |
| `secondbrain who "<name>"` | Person card across every source that mentions them. |
| `secondbrain digest --period day` | Daily/weekly/monthly reflection. Add `--llm` for LLM synthesis. |
| `secondbrain forget --capture-id <id> --reason <r>` | GDPR Art. 17 cascading delete. |
| `secondbrain ui` | Launch the Tauri desktop app + HTTP gateway. |
| `secondbrain mcp` | FastMCP stdio server for Claude Desktop / Cursor / Codex. |
| `secondbrain mcp-doctor` | Diagnostic + paste-ready MCP client config. |
| `secondbrain preflight` | Verify TCC permissions, sidecars, and dependencies. |
| `secondbrain install-agent` / `uninstall-agent` / `agent-status` | macOS launchd integration. |
| `secondbrain backup <path>` / `restore <path>` | Encrypted snapshot + restore. |
| `secondbrain status` | Capture and storage metrics. |

## Configuration

SecondBrain is configured by environment variables — no config file required for the local-only default. To point it at a hosted LLM, install the matching extra and export three vars:

```bash
# 1. Install the SDK for your chosen provider.
pip install -e '.[openai]'         # or [anthropic] / [gemini] / [groq] / [mistral]
                                    # or [byo-llm] for all five at once

# 2. Tell SecondBrain to use it.
export SECONDBRAIN_LLM_PROVIDER=openai         # ollama (default) | openai | anthropic
                                                # | gemini | groq | mistral
export SECONDBRAIN_LLM_MODEL=gpt-4o-mini       # any model the provider serves
export SECONDBRAIN_LLM_API_KEY=sk-...          # not needed for local Ollama
# export SECONDBRAIN_LLM_BASE_URL=...          # only for self-hosted endpoints

# 3. Verify.
secondbrain mcp-doctor                          # prints loaded providers + warnings
```

Captures, embeddings, KG nodes, and the audit log never leave your device. With a hosted LLM, only the prompted text egresses — and only on the calls you opted into.

## Contributing

Contributions are welcome. Before opening a PR:

1. Browse `src/secondbrain/` — modules are organised by pipeline stage (`capture/`, `memory/`, `store/`, `search/`, `api/`).
2. Run the deterministic suite: `pytest tests/ --ignore=tests/test_macos_sck.py --ignore=tests/test_ocr.py` (no network, no TCC required).
3. Project conventions: Pydantic models across module boundaries, heuristic fallback for every LLM hot path, capture IDs as hex UUIDs.

Questions, ideas, and bug reports go in [GitHub Discussions](https://github.com/openintelligence-labs/secondbrain/discussions) and [Issues](https://github.com/openintelligence-labs/secondbrain/issues).

## Star history

<a href="https://star-history.com/#openintelligence-labs/secondbrain&Date">
  <img src="https://api.star-history.com/svg?repos=openintelligence-labs/secondbrain&type=Date" alt="Star history" width="640"/>
</a>

## License

[MIT](LICENSE) © Open Intelligence Labs.
