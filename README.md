# SecondBrain

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Powered by actants](https://img.shields.io/badge/powered%20by-actants-7c3aed)](https://github.com/openintelligence-labs/actants)

> **Personal AI memory — local alternative to Rewind.ai.** Continuously indexes your screen, documents, and browser history with OCR and embeddings. Ask natural questions like *"what was that restaurant my friend mentioned last Tuesday?"* and find it instantly.

⭐ **Star us on GitHub** if you've ever forgotten something you definitely saw.

## Why this exists

Rewind.ai was $25/mo and shut down. Windows Recall had a privacy scandal. Screenpipe exists but is buggy and narrow. The "total recall for your digital life" problem is unsolved in open source. SecondBrain fixes that — entirely on your machine.

## Quick start

```bash
pip install secondbrain
secondbrain index
secondbrain search "that article about quantum computing"
```

## Features

| Feature | What it does |
|---|---|
| Document indexing | Markdown, PDFs, notes, emails |
| Screen OCR | Continuously index what you see (opt-in) |
| Browser history | Import bookmarks + history |
| Semantic search | Natural language queries via sqlite-vec |
| Timeline view | Scroll your digital life |
| 100% local | Nothing leaves your machine |

## Roadmap

- [x] Chunking with overlap
- [x] CLI skeleton
- [ ] Document ingestion pipeline
- [ ] Embedding via actants
- [ ] sqlite-vec storage
- [ ] Query rewriting + retrieval
- [ ] Screen OCR daemon
- [ ] Timeline UI

## Part of the Open Intelligence Labs ecosystem

- [actants](https://github.com/openintelligence-labs/actants) — shared SDK + embeddings
- [DeepDive](https://github.com/openintelligence-labs/deepdive) — uses the same embedding pipeline
- [MeetMind](https://github.com/openintelligence-labs/meetmind) — meeting transcripts flow into your second brain

## License

MIT
