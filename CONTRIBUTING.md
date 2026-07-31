# Contributing to SecondBrain

Thanks for considering a contribution. SecondBrain holds the most sensitive data on a user's machine, so contributions are held to a matching standard — especially anything touching capture, storage, or the network.

## The one rule that isn't negotiable

**Captured data stays on the device.** Captures, OCR text, embeddings, the knowledge graph, and the audit log never leave the machine. The only egress is the LLM transport the user explicitly configured, which defaults to local Ollama. Any PR that adds telemetry, analytics, crash reporting, remote logging, or a "just this one anonymous metric" phone-home will be closed regardless of quality.

We also don't pitch SecondBrain as "100% local" — that's only true for users who can host a model. The framing is **local-by-default, BYO-LLM, never phones home unless you point it at a hosted provider.** Please keep docs consistent with that.

## Dev setup

```bash
git clone https://github.com/openintelligence-labs/secondbrain
cd secondbrain
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,ml]'
.venv/bin/pytest
```

On macOS, the capture sidecars need a Swift build:

```bash
cd swift/SecondBrainCapture && swift build -c release
```

The full suite runs without network access. LLM tests skip when Ollama isn't reachable; macOS capture tests skip without TCC permissions granted. If you're not on macOS, expect those to skip — that's normal, not a broken checkout.

## Before opening a PR

- `ruff check .` passes
- `ruff format --check .` passes
- `pytest` passes
- New public functions have docstrings
- Anything crossing a module boundary uses a Pydantic model
- Tests still pass with no network

## Where things live

| Area | Path |
|---|---|
| Capture, dedup cascade, deny-list | `src/secondbrain/capture/` |
| OCR bridge + selector policy | `src/secondbrain/ocr/` |
| Embedders (local + BYO) | `src/secondbrain/embed/` |
| Encrypted SQLite, LanceDB, tantivy, Kùzu | `src/secondbrain/store/` |
| Hybrid retrieval + reranking | `src/secondbrain/search/` |
| Extraction, linking, digests, decay | `src/secondbrain/memory/` |
| MCP server + tools | `src/secondbrain/api/` |
| Audit log, air-gap, classifiers | `src/secondbrain/compliance/` |

Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before non-trivial changes — stack decisions, module boundaries, and roadmap live there.

## Contributions we especially want

- **Wearable importers.** `src/secondbrain/capture/wearable/` already has Plaud, OMI, Limitless, Bee, and Rewind. More devices are welcome — mirror the shape of an existing importer and add a fixture-driven test.
- **Non-macOS capture backends.** Linux and Windows capture are the biggest gaps.
- **Retrieval quality.** Improvements to the hybrid cascade are welcome if you bring evaluation numbers, not vibes.
- **Cascade performance.** The gates run cheapest-first; making an early gate cheaper helps every capture.

## Things to be careful with

- **Capture path changes** need a test proving the deny-list still holds.
- **Storage changes** need a migration story and must not write plaintext outside the encrypted stores.
- **`memory.forget` changes** must delete from *every* store — OLTP, LanceDB, tantivy, Kùzu, and on-disk artifacts. Add a test that asserts the data is gone from all of them.
- **New dependencies** need justification. Heavy ML deps belong behind an extra, not in the base install.

## Security issues

Don't open a public issue. See [SECURITY.md](SECURITY.md) — report privately through GitHub Security Advisories.
