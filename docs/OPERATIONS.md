# SecondBrain — Operations Runbook

Concrete commands for running SecondBrain as a 24/7 macOS daemon. Each
section is a self-contained recipe; you should not need to read the rest
of `docs/` to do any of these.

---

## 1. Install + launch at login

```bash
pip install -e '.[dev]'                      # one-time
swift build -c release --package-path swift/SecondBrainCapture
secondbrain mcp-doctor                        # sanity check (paths, LLM SDK)
secondbrain install-agent                     # writes the LaunchAgent plist
```

What `install-agent` does:

- Writes `~/Library/LaunchAgents/com.openintelligencelabs.secondbrain.plist`.
- Bootstraps it (`launchctl bootstrap gui/<uid> …`).
- The daemon now starts at every login. Output logs land at
  `~/.secondbrain/logs/secondbrain.{out,err}.log`.

Pass-through flags for `secondbrain run` go via `--extra-arg`:

```bash
secondbrain install-agent --extra-arg --ocr-fallback --extra-arg --llm
```

To remove:

```bash
secondbrain uninstall-agent
```

To inspect status:

```bash
secondbrain agent-status        # plist present + launchctl loaded
```

---

## 2. Run the desktop UI

```bash
cd app && npm install && npm run build
. "$HOME/.cargo/env" && (cd src-tauri && cargo build --release)
secondbrain ui                  # starts gateway + launches Tauri
```

The UI talks to the gateway at `http://127.0.0.1:7821`. If you already have
the daemon running via LaunchAgent, prefer:

```bash
secondbrain ui-gateway          # just the gateway, no Tauri
```

…then open the app directly: `app/src-tauri/target/release/secondbrain-app`.

---

## 3. Backup + restore

```bash
secondbrain backup ~/Desktop/sb-2026-05-12.tar.gz
# …later…
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.openintelligencelabs.secondbrain.plist"   # stop the daemon FIRST
secondbrain restore --force ~/Desktop/sb-2026-05-12.tar.gz
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.openintelligencelabs.secondbrain.plist"
```

The archive contains: encrypted SQLite, LanceDB vectors, tantivy index, Kùzu KG.
Restore validates every file's SHA-256 against the manifest before swapping in;
a tampered or partial archive aborts cleanly.

Schema version is recorded in the manifest. Restoring an archive whose
`schema_version` is *newer* than your installed SecondBrain refuses with a
clear error — upgrade SecondBrain first.

---

## 4. Database recovery

When `/health` returns 503 with `oltp.ok = false`, or
`secondbrain status` raises `IntegrityCheckFailed`:

```bash
secondbrain agent-status                              # confirm not running
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.openintelligencelabs.secondbrain.plist
# If you have a backup — preferred:
secondbrain restore --force ~/Desktop/sb-LATEST.tar.gz

# If you don't, last-resort recovery: dump what's salvageable:
python -c "from secondbrain.store.oltp import open_unencrypted; \
  conn = open_unencrypted('$HOME/.secondbrain/secondbrain.db', check_integrity=False); \
  print(conn.execute('SELECT COUNT(1) FROM captures').fetchone())"
```

After recovery, re-load the agent.

---

## 5. Health + metrics for monitoring

```bash
curl -s http://127.0.0.1:7821/health | jq
curl -s http://127.0.0.1:7821/metrics
```

`/health` returns 200 when OLTP is reachable AND disk free ≥ 1 GiB AND (if a
daemon is attached) the daemon is alive. 503 otherwise. The `checks` map
reports per-component status — read it before paging.

`/metrics` is Prometheus text format. Useful metric names:

- `secondbrain_captures_persisted_total` — counter
- `secondbrain_captures_by_gate_total{gate="dhash"}` — cascade gate counts
- `secondbrain_ax_text_ratio` — gauge, % of captures with AX text (close to 1
  is healthy; sudden drop usually means an app changed its AX-tree shape)
- `secondbrain_memory_linker_failures_total` — A-MEM linker fell back
- `secondbrain_memory_commitment_failures_total` — LLM commitment extractor
  fell back to heuristic (any non-zero rate during steady state means the LLM
  is degraded — check `/llm-config`)
- `secondbrain_daemon_paused` — 1 when paused via tray or `/daemon`

Scrape recipe for a local Prometheus:

```yaml
- job_name: secondbrain
  static_configs:
    - targets: ['127.0.0.1:7821']
```

---

## 6. GDPR Article 17 — forget a person or capture

```bash
secondbrain forget --capture-id <hex-id> --reason "user-requested redact"
secondbrain forget --person "Sam Reed"  --reason "user-requested redact"
```

Both flows:

1. Cascade-delete the capture / person node and every MemoryNode that only
   derives from it.
2. Write an `audit_log` row (action=`forget`, signed via HMAC-SHA256 in
   exports).

The UI exposes the same flow: right-click any row in **Timeline** → "Forget
this memory". Audit-log rows are visible in **Settings** → "Audit log".

---

## 7. Switch / configure the LLM provider

```bash
# Default: local Ollama (no env vars needed).
ollama pull llama3.1
secondbrain run --llm

# BYO-LLM — Anthropic:
pip install 'secondbrain[anthropic]'
export SECONDBRAIN_LLM_PROVIDER=anthropic
export SECONDBRAIN_LLM_MODEL=claude-opus-4-7
export SECONDBRAIN_LLM_API_KEY=sk-ant-…
secondbrain run --llm
```

To verify the runtime is wired correctly:

```bash
secondbrain mcp-doctor
curl -s http://127.0.0.1:7821/llm-config | jq
```

If `sdk_state` is `missing:<sdk>`, the matching extra wasn't installed —
re-run `pip install 'secondbrain[<provider>]'`.

---

## 8. Air-gap mode

Engages a Python-level socket guard: any non-loopback outbound `connect()`
raises `AirGapViolation`.

```bash
secondbrain --offline run --db ~/.secondbrain/secondbrain.db
```

Use this when running fully locally and you want belt-and-braces enforcement
that nothing phones home — even if a transitive HTTP client is misconfigured.
Note: air-gap is process-level, so combine with `--llm` only when the LLM
backend is `ollama` (loopback).

---

## 9. Multi-device sync (Syncthing)

v1.0 sync uses a Syncthing-watched folder as the transport. SecondBrain writes
encrypted JSON blobs into the folder; Syncthing distributes them; the other
device's `secondbrain pull` reads and applies.

```bash
# Both devices:
brew install syncthing
mkdir -p ~/SecondBrainSync
# Point Syncthing at ~/SecondBrainSync on both devices.

# Pair the devices (one-time) — generates a 32-byte PSK from X25519 DH.
secondbrain pair --folder ~/SecondBrainSync   # NOTE: pair CLI lands in v1.0
```

Important: add `.seen/` to Syncthing's `.stignore` for that folder so per-
device "what have I already pulled" state stays local. The data root itself
(`~/.secondbrain/`) is NEVER added to Syncthing — that's encrypted SQLite, and
Syncthing's chunking would corrupt the SQLCipher format.

Sync **policy** is locked: structured facts + dense embeddings cross devices;
raw HEVC frames and audio do not. See `src/secondbrain/sync/policy.py`.

---

## 10. Common failure modes (quick reference)

| Symptom | First diagnosis | Fix |
|---|---|---|
| `/health` 503, `oltp.ok=false` | DB closed / corrupt | restore from backup; see §4 |
| `/health` 503, `disk.free_gib < 1` | full disk | move backups off, clear `~/.secondbrain/logs` |
| `secondbrain_memory_commitment_failures_total` climbing | LLM degraded | `/llm-config`, restart Ollama, or unset `--llm` |
| Capture metrics frozen (no new `persisted` counts) | TCC permission revoked | System Settings → Privacy → Screen Recording |
| Sidecar restart counter climbing | Swift sidecar crashing | tail `~/.secondbrain/logs/secondbrain.err.log` |
| `AirGapViolation` thrown but you want network | `--offline` is set | remove the flag |

---

## 11. Where things live

```
~/.secondbrain/
├── secondbrain.db          # encrypted OLTP (captures + audit log)
├── lance/                  # LanceDB chunk vectors
├── tantivy/                # BM25 index
├── kg/                     # Kùzu knowledge graph
├── lance_visual/           # (optional) ColQwen2.5 visual patches
└── logs/
    ├── secondbrain.out.log
    └── secondbrain.err.log

~/Library/LaunchAgents/com.openintelligencelabs.secondbrain.plist
~/Library/Keychains/login.keychain → service "secondbrain.device_root_key"
```

The Keychain item is the *only* secret on disk that lives outside
`~/.secondbrain/`. Lose it and the OLTP DB is permanently unreadable. The
pairing flow's recovery phrase is the user-facing escape hatch.
