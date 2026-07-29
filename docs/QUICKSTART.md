# SecondBrain — Quickstart

A working setup on macOS, from zero to "you can see the app."

## Prerequisites

```bash
# Python 3.13+, Rust toolchain, Node 24+
node --version    # >= 24
python3 --version # >= 3.13
. "$HOME/.cargo/env" && cargo --version || curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
```

## Build (one-time, ~3 min)

```bash
cd secondbrain

# Python core
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

# Swift sidecars (capture + OCR)
cd swift/SecondBrainCapture && swift build -c release && cd ../..

# Tauri shell — frontend + Rust backend
cd app
npm install
npm run build
. "$HOME/.cargo/env" && cd src-tauri && cargo build --release && cd ../..
```

## See it working

There are two paths. The demo path proves the engine without needing macOS TCC permissions; the live path is what you'd use day-to-day.

### Demo path (no permissions required)

```bash
# Seed a fixture workday + run every CLI command end-to-end.
./demo.sh

# Or capture the full transcript:
DEMO_RECORD=1 ./demo.sh && open docs/DEMO_RUN.md
```

`docs/DEMO_RUN.md` is a real captured run of the shipping CLI showing search,
who, digest, mcp-doctor, and a cascading GDPR forget.

### Live path (needs Screen Recording + Accessibility TCC)

```bash
# 1. Grant the binaries TCC permission once:
#    System Settings → Privacy & Security
#      → Screen Recording: enable `secondbrain-capture`
#      → Accessibility:   enable `Terminal` (or whatever shell launches the daemon)
#
# 2. Start the capture daemon (in one terminal):
.venv/bin/secondbrain run --fps 1

# 3. Open the desktop UI (in another terminal):
.venv/bin/secondbrain ui --no-encryption --stub-embedder --db ~/.secondbrain/secondbrain.db
#    This launches the Tauri app + HTTP gateway in one command.
#    A window appears showing today's captures.
#    Press ⌘+Space anywhere to summon the search overlay.

# 4. (Optional) Wire Claude Desktop to SecondBrain memory:
.venv/bin/secondbrain mcp-doctor
#    Copy the printed JSON into:
#    ~/Library/Application Support/Claude/claude_desktop_config.json
#    Restart Claude → ask "what memory tools do you have?"
```

## What you'll see

`docs/screenshots/timeline.png` is a real screenshot of the app rendering 7
demo-seeded captures, with amber commitment markers, JetBrains Mono body,
Newsreader italic title, and a 1px-hairline zinc-950 background.

## Common issues

- **"GATEWAY OFFLINE" in the UI.** The `secondbrain ui` command starts the
  HTTP gateway as a background thread. If you're running the binary
  directly without `secondbrain ui`, also run `secondbrain ui-gateway` in a
  separate terminal.
- **Blank window.** Rebuild the Tauri binary with `cargo build --release`
  after every `tauri.conf.json` or `dist/` change. The frontend is embedded
  into the binary at compile time.
- **`secondbrain-capture` "no displays available."** Screen Recording TCC
  was revoked — macOS does this when binary modtimes change. Re-grant.
- **`secondbrain run` shows `app=None`.** Accessibility TCC was revoked
  on the parent shell. Re-grant the shell.
