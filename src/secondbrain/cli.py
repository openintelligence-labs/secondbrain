"""SecondBrain CLI."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC
from pathlib import Path

import click

from secondbrain.capture.frame import Frame, SyntheticFrameSource, now
from secondbrain.daemon import Daemon, DaemonConfig
from secondbrain.store import captures as captures_repo
from secondbrain.store.oltp import StoreConfig, open_encrypted

DEFAULT_DB = Path.home() / ".secondbrain" / "secondbrain.db"


@click.group()
@click.option(
    "--offline",
    is_flag=True,
    help="Engage air-gap mode: every non-loopback outbound connect raises "
    "AirGapViolation. Use when running against a fully-local LLM and you "
    "want belt-and-braces enforcement that nothing phones home.",
)
@click.pass_context
def main(ctx: click.Context, offline: bool) -> None:
    """SecondBrain — personal AI memory."""
    if offline:
        from secondbrain.compliance.air_gap import engage

        engage()
        click.echo("[air-gap engaged] all non-loopback outbound connects will fail", err=True)
    ctx.ensure_object(dict)
    ctx.obj["offline"] = offline


def _searcher(db: Path, *, use_stub: bool):
    from secondbrain.embed.stub import StubEmbedder
    from secondbrain.embed.text import TextEmbedder
    from secondbrain.search.hybrid import HybridSearcher
    from secondbrain.store.text_index import TextIndex
    from secondbrain.store.vector import VectorStore

    base = db.parent
    vector = VectorStore(db_path=base / "lance")
    text = TextIndex(index_path=base / "tantivy")
    embedder: object
    embedder = StubEmbedder() if use_stub else TextEmbedder()
    return HybridSearcher(text_index=text, vector_store=vector, embedder=embedder)


@main.command()
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option(
    "--stub-embedder", is_flag=True, help="Use deterministic stub embedder (tests/dev only)"
)
@click.option("--no-encryption", is_flag=True, help="Open OLTP DB unencrypted")
def index(db: Path, stub_embedder: bool, no_encryption: bool) -> None:
    """Re-index every capture in the OLTP store into LanceDB + tantivy."""
    from datetime import datetime

    from secondbrain.embed.stub import StubEmbedder
    from secondbrain.embed.text import TextEmbedder
    from secondbrain.indexing import Indexer
    from secondbrain.models import Capture
    from secondbrain.store import captures as captures_repo
    from secondbrain.store.oltp import StoreConfig, open_encrypted, open_unencrypted
    from secondbrain.store.text_index import TextIndex
    from secondbrain.store.vector import VectorStore

    if not db.exists():
        click.echo(f"No DB at {db}. Run capture first.")
        return
    if no_encryption:
        conn = open_unencrypted(db)
    else:
        try:
            conn = open_encrypted(StoreConfig(db_path=db))
        except Exception:
            conn = open_unencrypted(db)

    base = db.parent
    embedder: object = StubEmbedder() if stub_embedder else TextEmbedder()
    indexer = Indexer(
        embedder=embedder,
        vector=VectorStore(db_path=base / "lance"),
        text=TextIndex(index_path=base / "tantivy"),
    )
    rows = list(captures_repo.recent(conn, limit=100_000))
    n_chunks = 0
    for row in rows:
        cap = Capture(
            id=row["id"],
            captured_at=datetime.fromtimestamp(row["captured_at"], tz=UTC),
            app_name=row.get("app_name"),
            app_bundle_id=row.get("app_bundle_id"),
            window_title=row.get("window_title"),
            url=row.get("url"),
            ax_text=row.get("ax_text"),
            ocr_text=row.get("ocr_text"),
        )
        n_chunks += indexer.index_capture(cap)
    click.echo(f"indexed: captures={len(rows)} chunks={n_chunks}")


@main.command()
@click.argument("query")
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--limit", type=int, default=10)
@click.option("--rerank/--no-rerank", default=False, help="Apply mxbai-rerank-base-v2")
@click.option("--stub-embedder", is_flag=True)
@click.option("--no-encryption", is_flag=True, help="(reserved; OLTP not opened in search)")
def search(
    query: str, db: Path, limit: int, rerank: bool, stub_embedder: bool, no_encryption: bool
) -> None:
    """Search captures (BM25 ⊕ dense → RRF k=60 → optional rerank)."""
    searcher = _searcher(db, use_stub=stub_embedder)
    hits = searcher.search(query, limit=limit if not rerank else max(limit, 50))

    if rerank and hits:
        from secondbrain.search.rerank import Reranker

        rr = Reranker()
        ranking = rr.rerank(query, [h.body for h in hits], top_k=limit)
        hits = [hits[i] for i, _ in ranking]
    else:
        hits = hits[:limit]

    if not hits:
        click.echo("(no hits)")
        return
    for h in hits:
        snippet = (h.body or "").replace("\n", " ")[:200]
        click.echo(
            f"[{h.rrf_score:.4f}] {h.capture_id}#{h.chunk_index}  "
            f"bm25={h.bm25_rank!s:>4}  dense={h.dense_rank!s:>4}\n"
            f"    {snippet}"
        )


@main.command()
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option(
    "--no-encryption",
    is_flag=True,
    help="Open DB unencrypted (dev/tests only — never use in prod)",
)
def status(db: Path, no_encryption: bool) -> None:
    """Show capture counts, gate hit rates, AX-vs-OCR ratio."""
    if not db.exists():
        click.echo(f"No DB at {db}. Has the daemon run yet?")
        return
    if no_encryption:
        from secondbrain.store.oltp import open_unencrypted

        conn = open_unencrypted(db)
    else:
        conn = open_encrypted(StoreConfig(db_path=db))
    total = captures_repo.count(conn)
    click.echo(f"captures: {total}")
    if total == 0:
        return
    rows = list(captures_repo.recent(conn, limit=5))
    click.echo("recent:")
    for r in rows:
        click.echo(
            f"  {r['captured_at']:.0f}  {r['app_name']!s:>20}  "
            f"{r['gate']!s:>10}  {r.get('window_title', '')!s}"
        )


@main.command()
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--fps", type=int, default=1)
@click.option("--display", type=int, default=0)
@click.option("--max-frames", type=int, default=-1, help="-1 = run until SIGINT")
@click.option(
    "--no-encryption",
    is_flag=True,
    help="Open DB unencrypted (dev/tests only)",
)
@click.option(
    "--stub-embedder", is_flag=True, help="Use deterministic stub embedder (skip Nomic v2 download)"
)
@click.option(
    "--visual", is_flag=True, help="Also embed each persisted frame with ColQwen2.5 (slow)"
)
@click.option(
    "--no-memory", is_flag=True, help="Skip embedding + KG ingestion entirely (capture-only)"
)
@click.option(
    "--ocr-fallback", is_flag=True, help="Run Apple Vision OCR when AX text is empty (macOS only)"
)
@click.option(
    "--llm",
    is_flag=True,
    help="Route importance + commitments + digest through actants LLM (Ollama)",
)
@click.option("--llm-model", default=None, help="Override the actants LLM model")
@click.option(
    "--llm-embeddings", is_flag=True, help="Also route embeddings through actants (Ollama)"
)
@click.option(
    "--redact",
    is_flag=True,
    help="Enable sensitive-content redaction gate (heuristic baseline; "
    "Florence-backed model lands behind the [redact] extra in v0.3)",
)
@click.option(
    "--redact-threshold",
    type=float,
    default=0.6,
    help="Confidence threshold above which a frame is redacted (default 0.6)",
)
def run(
    db: Path,
    fps: int,
    display: int,
    max_frames: int,
    no_encryption: bool,
    stub_embedder: bool,
    visual: bool,
    no_memory: bool,
    ocr_fallback: bool,
    llm: bool,
    llm_model: str | None,
    llm_embeddings: bool,
    redact: bool,
    redact_threshold: float,
) -> None:
    """Run the macOS capture daemon for real (ScreenCaptureKit + cascade + encrypted DB)."""
    from secondbrain.capture.macos_sck import MacOSScreenSource

    src = MacOSScreenSource(
        pixel_mode="png",
        fps=fps,
        display_index=display,
        max_frames=max_frames,
    )
    cfg = DaemonConfig(
        db_path=db,
        use_encryption=not no_encryption,
        use_stub_embedder=stub_embedder,
        enable_memory=not no_memory,
        enable_visual=visual,
        enable_ocr_fallback=ocr_fallback,
        enable_llm=llm,
        llm_model=llm_model,
        llm_embeddings=llm_embeddings,
        enable_redact=redact,
        redact_threshold=redact_threshold,
    )
    daemon = Daemon(cfg)

    async def go() -> None:
        await daemon.run(src)

    asyncio.run(go())
    click.echo(json.dumps(daemon.metrics.as_dict(), indent=2))


@main.command()
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--stub-embedder", is_flag=True, help="Use stub embedder (skips Nomic v2 download)")
def mcp(db: Path, stub_embedder: bool) -> None:
    """Run the MCP stdio server. Connect Claude Desktop / Cursor / Codex via this command."""
    from secondbrain.api.mcp_stdio import serve

    serve(db=db, use_stub_embedder=stub_embedder)


@main.command(name="ui-gateway")
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--host", default="127.0.0.1")
@click.option("--port", type=int, default=7821)
@click.option("--stub-embedder", is_flag=True, help="Use stub embedder (skip Nomic v2)")
@click.option("--no-encryption", is_flag=True, help="Open OLTP unencrypted (dev only)")
def ui_gateway(db: Path, host: str, port: int, stub_embedder: bool, no_encryption: bool) -> None:
    """Run the 127.0.0.1 HTTP gateway the Tauri UI talks to."""
    from secondbrain.api.http import GatewayConfig
    from secondbrain.api.http import serve as serve_gateway
    from secondbrain.api.mcp_server import make_default_context

    ctx = make_default_context(db=db, use_stub_embedder=stub_embedder)
    cfg = GatewayConfig(host=host, port=port)
    click.echo(f"secondbrain UI gateway listening on http://{host}:{port}")
    asyncio.run(serve_gateway(ctx, cfg=cfg))


@main.command()
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--fps", type=int, default=1, help="ScreenCaptureKit frame rate")
@click.option(
    "--demo",
    is_flag=True,
    help="Throwaway mode: synthetic frames, stub embedder, no encryption, "
    "no LLM. Useful for screenshots / UI dev. Default is the production stack.",
)
@click.option(
    "--skip-preflight",
    is_flag=True,
    help="Skip the host audit. You almost never want this — preflight tells "
    "you exactly what's missing.",
)
@click.option(
    "--no-llm",
    is_flag=True,
    help="Disable Ollama routing (heuristics only). Default is --llm on.",
)
def ui(
    db: Path,
    fps: int,
    demo: bool,
    skip_preflight: bool,
    no_llm: bool,
) -> None:
    """Launch the Tauri desktop UI on the full production stack.

    Default behavior:
      * ScreenCaptureKit captures real frames (TCC permission required)
      * Encrypted SQLite (SQLCipher AES-256, key in Keychain)
      * Nomic v2 dense embeddings (~500MB one-time download)
      * Ollama LLM for importance + commitments + digest (heuristic fallback)

    Pass --demo to swap in synthetic frames + stub embedder + plain SQLite
    for screenshots / UI dev.
    """
    import os
    import subprocess
    import sys as _sys
    import threading
    import time

    from secondbrain.api.http import GatewayConfig, make_app
    from secondbrain.capture.frame import (
        Frame,
        LoopingSyntheticSource,
    )
    from secondbrain.capture.frame import (
        now as _now,
    )
    from secondbrain.daemon import Daemon, DaemonConfig
    from secondbrain.preflight import gate, run_preflight

    # Prefer the release build, fall back to debug.
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "app" / "src-tauri" / "target" / "release" / "secondbrain-app",
        repo_root / "app" / "src-tauri" / "target" / "debug" / "secondbrain-app",
    ]
    binary = next((c for c in candidates if c.exists()), None)
    if binary is None:
        raise click.ClickException(
            "Tauri binary not built. Run: cd app && npm install && npm run build && "
            '(. "$HOME/.cargo/env" && cd src-tauri && cargo build --release)'
        )

    if not demo and not skip_preflight:
        click.echo("running preflight…", err=True)
        checks = run_preflight(db, probe_tcc=True)
        for c in checks:
            click.echo(str(c), err=True)
        ok, blockers = gate(checks)
        if not ok:
            click.echo("", err=True)
            click.echo(
                f"✗ {len(blockers)} blocker(s). Fix above, or pass --demo for the "
                "synthetic stack, or --skip-preflight to bypass.",
                err=True,
            )
            raise click.ClickException("preflight failed")
        click.echo("", err=True)

    # The Daemon owns every stateful handle (OLTP, KG, LanceDB, tantivy) and
    # the gateway borrows them via mcp_context(). Sharing is mandatory: each
    # store takes an exclusive process-wide lock on its on-disk files.
    cfg = DaemonConfig(
        db_path=db,
        use_encryption=not demo,
        use_stub_embedder=demo,
        enable_memory=True,
        enable_llm=(not demo) and (not no_llm),
        enable_ocr_fallback=not demo,
    )
    daemon = Daemon(cfg)
    daemon.build_pipeline()
    ctx = daemon.mcp_context()

    if not demo:
        from secondbrain.capture.macos_sck import MacOSScreenSource

        source = MacOSScreenSource(pixel_mode="png", fps=fps, display_index=0, max_frames=-1)
        src_label = f"ScreenCaptureKit @{fps}fps"
    else:
        # Loop a small set of synthetic frames forever so the UI has live data.
        import numpy as np
        from PIL import Image

        rng = np.random.default_rng(0)
        samples = [
            "Sam Reed will ship the Snowflake migration by Friday.",
            "Kafka consumer lag spiked at 14:02 on the ingest pipeline.",
            "Stripe billing token expiry hotfix shipped Wednesday afternoon.",
            "Weekend hike notes — golden gate trail conditions are dry.",
            "Linda merged the dashboard branch and asked for a review.",
            "Standup notes: Q2 roadmap finalized; demo on Thursday.",
        ]
        templates: list[Frame] = []
        for i, text in enumerate(samples):
            arr = rng.integers(0, 255, size=(240, 320, 3), dtype=np.uint8)
            templates.append(
                Frame(
                    captured_at=_now(),
                    image=Image.fromarray(arr),
                    app_name=f"DemoApp{i % 3}",
                    app_bundle_id=f"com.demo.app{i % 3}",
                    window_title=f"Window {i}",
                    ax_text=text,
                    dirty_rect_fraction=0.5,
                )
            )
        source = LoopingSyntheticSource(templates, interval_s=1.5)
        src_label = "synthetic frames @1.5s (--sck for real capture)"

    # Run gateway + daemon in one event loop on a background thread.
    gw_cfg = GatewayConfig(host="127.0.0.1", port=7821)

    async def _run_everything():
        from aiohttp import web as _web

        app = make_app(ctx, daemon=daemon, cfg=gw_cfg)
        runner = _web.AppRunner(app)
        await runner.setup()
        site = _web.TCPSite(runner, gw_cfg.host, gw_cfg.port)
        await site.start()
        try:
            await daemon.run(source)
        finally:
            await runner.cleanup()

    def _thread_target():
        try:
            asyncio.run(_run_everything())
        except Exception as e:
            click.echo(f"daemon/gateway exited: {e!r}", err=True)

    t = threading.Thread(target=_thread_target, daemon=True)
    t.start()

    # Wait for gateway to be ready before launching the UI.
    import urllib.request

    deadline = time.time() + 8
    gateway_up = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:7821/health", timeout=0.5):
                gateway_up = True
                break
        except Exception:
            time.sleep(0.1)
    if not gateway_up:
        raise click.ClickException("gateway didn't come up within 8s")

    mode = "DEMO" if demo else "PRODUCTION"
    click.echo(f"secondbrain UI [{mode}] · gateway → http://127.0.0.1:7821")
    click.echo(f"   capture: {src_label}")
    click.echo(f"   encryption: {'off (demo)' if demo else 'SQLCipher AES-256'}")
    click.echo(f"   embeddings: {'stub (demo)' if demo else 'Nomic v2'}")
    click.echo(f"   LLM: {'off' if (demo or no_llm) else 'Ollama (heuristic fallback)'}")
    click.echo(f"   binary: {binary}")
    env = os.environ.copy()
    try:
        rc = subprocess.call([str(binary)], env=env)
    finally:
        daemon.stop()
    _sys.exit(rc)


@main.command(name="mcp-doctor")
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
def mcp_doctor(db: Path) -> None:
    """Check the MCP runtime + print a Claude Desktop config block ready to paste."""
    import platform
    import shutil as _shutil
    import sys as _sys

    click.echo(f"secondbrain version  : {__import__('secondbrain').__version__}")
    click.echo(f"python version       : {_sys.version.split()[0]}")
    click.echo(f"platform             : {platform.system()} {platform.release()}")
    click.echo(
        f"db path              : {db} ({'exists' if db.exists() else 'absent — run capture first'})"
    )
    bin_path = _shutil.which("secondbrain")
    click.echo(f"secondbrain binary   : {bin_path or '(not on PATH)'}")

    from secondbrain.llm_config import from_env

    llm_cfg = from_env()
    click.echo(f"LLM config           : {llm_cfg.describe()}")

    # A missing provider SDK is the second-most-common BYO-LLM failure mode
    # after a forgotten API key.
    if llm_cfg.provider:
        import importlib.util as _ilu

        sdk_for: dict[str, str | None] = {
            "ollama": None,
            "openai": "openai",
            "anthropic": "anthropic",
            "gemini": None,  # uses httpx (already in deps)
            "groq": "openai",  # OpenAI-compatible
            "mistral": "openai",  # OpenAI-compatible
        }
        prov = llm_cfg.provider.lower()
        if prov not in sdk_for:
            click.echo(
                f"LLM SDK              : WARN — provider '{prov}' is not in the "
                "actants 6-provider set; LLM construction will raise."
            )
        else:
            required = sdk_for[prov]
            if required is None:
                click.echo(f"LLM SDK              : OK ({prov} needs no extra)")
            elif _ilu.find_spec(required) is None:
                click.echo(
                    f"LLM SDK              : MISSING — '{required}' not importable. "
                    f"Fix: pip install secondbrain[{prov}]"
                )
            else:
                click.echo(f"LLM SDK              : OK ({required} importable)")

    if bin_path is None:
        click.echo("\nFix: add this venv's bin/ to PATH or symlink secondbrain into /usr/local/bin")

    sb = bin_path or "secondbrain"
    db_str = str(db)
    click.echo("\nClaude Desktop config — paste into:")
    click.echo("  ~/Library/Application Support/Claude/claude_desktop_config.json\n")
    click.echo(
        json.dumps(
            {
                "mcpServers": {
                    "secondbrain": {
                        "command": sb,
                        "args": ["mcp", "--db", db_str],
                    }
                }
            },
            indent=2,
        )
    )
    click.echo(
        "\nThen restart Claude Desktop. Verify with: in Claude, ask "
        '"What memory tools do you have?"'
    )


@main.command()
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option(
    "--capture-id",
    "capture_id",
    default=None,
    help="Forget a single capture and any MemoryNodes only-derived from it",
)
@click.option(
    "--person",
    "person_name",
    default=None,
    help="Forget a Person + every MemoryNode mentioning them",
)
@click.option("--reason", required=True, help="Required justification, written into the audit log")
@click.option("--no-encryption", is_flag=True, help="Open OLTP unencrypted (dev/tests only)")
def forget(
    db: Path,
    capture_id: str | None,
    person_name: str | None,
    reason: str,
    no_encryption: bool,
) -> None:
    """Cascading delete + audit-log write — GDPR Art. 17 from the CLI."""
    if capture_id is None and person_name is None:
        raise click.UsageError("Specify --capture-id or --person")

    from secondbrain.compliance.audit import AuditLog
    from secondbrain.memory.entities import _stable_id
    from secondbrain.store.kg import KnowledgeGraph
    from secondbrain.store.oltp import open_unencrypted

    if no_encryption:
        oltp = open_unencrypted(db)
    else:
        try:
            oltp = open_encrypted(StoreConfig(db_path=db))
        except Exception:
            oltp = open_unencrypted(db)

    audit = AuditLog(oltp)
    kg = KnowledgeGraph(db_path=db.parent / "kg")
    n_deleted = 0

    if capture_id:
        n_deleted += kg.forget_capture(capture_id)
        click.echo(f"capture {capture_id}: deleted {n_deleted} derived MemoryNodes")
    if person_name:
        pid = _stable_id(person_name)
        kg._conn.execute("MATCH (p:Person {id:$id}) DETACH DELETE p", {"id": pid})
        click.echo(f"person {person_name} ({pid}): deleted")
    audit.record(
        "forget",
        actor="cli",
        detail={
            "capture_id": capture_id,
            "person": person_name,
            "reason": reason,
            "n_deleted": n_deleted,
        },
    )
    click.echo(f"audit log row written. reason={reason!r}")


@main.command()
@click.argument("name")
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--limit", type=int, default=10)
def who(name: str, db: Path, limit: int) -> None:
    """Show what we know about a person across all sources."""
    from secondbrain.memory.entities import _stable_id
    from secondbrain.store.kg import KnowledgeGraph

    kg = KnowledgeGraph(db_path=db.parent / "kg")
    pid = _stable_id(name)
    facts = kg.facts_about(pid, limit=limit)
    if not facts:
        click.echo(f"(no memories about {name})")
        return
    click.echo(f"Person: {name}  ({pid})")
    for f in facts:
        when = f["valid_from"].isoformat() if f["valid_from"] else "?"
        click.echo(f"  [{f['importance']:>4.1f}] {when}  {f['content'][:120]}")


@main.command()
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--period", type=click.Choice(["day", "week", "month"]), default="day")
@click.option("--day", type=str, default=None, help="ISO date (default: today UTC)")
@click.option(
    "--llm",
    is_flag=True,
    help="Synthesize themes via actants LLM (Ollama) instead of keyword counter",
)
@click.option("--llm-model", default=None, help="Override the actants LLM model")
def digest(db: Path, period: str, day: str | None, llm: bool, llm_model: str | None) -> None:
    """Render the reflection digest for a period."""
    from datetime import date as date_cls
    from datetime import datetime as dt

    from secondbrain.memory.digest import (
        render,
        use_actants_synthesizer,
        use_heuristic_synthesizer,
    )
    from secondbrain.store.kg import KnowledgeGraph

    if llm:
        use_actants_synthesizer(model=llm_model)

    kg = KnowledgeGraph(db_path=db.parent / "kg")
    on = dt.fromisoformat(day).date() if day else date_cls.today()
    digest = render(kg, period, day=on)  # type: ignore[arg-type]
    if llm:
        # Reset so a follow-up invocation in the same process is deterministic.
        use_heuristic_synthesizer()
    click.echo(f"Digest [{digest.period}] {digest.period_start.isoformat()}")
    click.echo(f"  importance_sum: {digest.importance_sum:.1f}")
    click.echo("  themes:")
    for t in digest.themes:
        click.echo(f"    - {t}")
    if digest.broken_promises:
        click.echo("  broken promises:")
        for b in digest.broken_promises:
            click.echo(f"    ! {b}")
    if digest.suggested_followups:
        click.echo("  follow-ups:")
        for f in digest.suggested_followups:
            click.echo(f"    > {f}")


@main.group()
def pair() -> None:
    """Device pairing for multi-device sync (Syncthing transport)."""


@pair.command(name="init")
def pair_init() -> None:
    """Generate (or print) this device's X25519 identity + fingerprint."""
    from secondbrain.sync.pair_store import load_or_create_identity

    ident = load_or_create_identity()
    click.echo("device pubkey   : " + ident.public_key_bytes.hex())
    click.echo("fingerprint hex : " + ident.fingerprint_hex())
    click.echo("fingerprint words: " + " ".join(ident.fingerprint_words()))
    click.echo("")
    click.echo("Send the pubkey above to your other device, then run on this device:")
    click.echo("  secondbrain pair complete <peer-pubkey-hex>")


@pair.command(name="show")
def pair_show() -> None:
    """Display the current device identity + whether a PSK is stored."""
    from secondbrain.sync.pair_store import load_or_create_identity, load_psk

    ident = load_or_create_identity()
    click.echo("device pubkey   : " + ident.public_key_bytes.hex())
    click.echo("fingerprint hex : " + ident.fingerprint_hex())
    psk = load_psk()
    if psk is None:
        click.echo("sync PSK         : (none — run `secondbrain pair complete <peer>`)")
    else:
        click.echo("sync PSK         : stored in Keychain (32 bytes)")


@pair.command(name="complete")
@click.argument("peer_pubkey_hex")
def pair_complete(peer_pubkey_hex: str) -> None:
    """Run X25519 DH against PEER_PUBKEY_HEX and store the derived 32-byte PSK
    in the Keychain. Idempotent — re-running overwrites the existing PSK."""
    from secondbrain.sync.pair_store import complete_pairing

    psk = complete_pairing(peer_pubkey_hex)
    click.echo(f"pairing complete — PSK stored in Keychain (sha256 prefix: {psk.hex()[:16]}…)")


@pair.command(name="forget")
def pair_forget() -> None:
    """Erase the stored PSK from the Keychain. The identity key is kept."""
    from secondbrain.sync.pair_store import clear_psk

    clear_psk()
    click.echo("PSK cleared. Re-run `secondbrain pair complete` to re-pair.")


@main.group()
def sync() -> None:
    """Push/pull MemoryNodes through a Syncthing-watched folder."""


def _sync_backend(folder: Path):
    from secondbrain.sync.backend import SyncthingBackend
    from secondbrain.sync.pair_store import load_psk

    psk = load_psk()
    if psk is None:
        raise click.ClickException(
            "no sync PSK stored. Run `secondbrain pair complete <peer-pubkey>` first."
        )
    return SyncthingBackend(folder=str(folder), psk=psk)


@sync.command(name="push")
@click.argument("folder", type=click.Path(path_type=Path))
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--no-encryption", is_flag=True)
def sync_push(folder: Path, db: Path, no_encryption: bool) -> None:
    """Push MemoryNodes newer than the cursor into FOLDER."""
    from secondbrain.store.kg import KnowledgeGraph
    from secondbrain.store.oltp import StoreConfig, open_encrypted, open_unencrypted
    from secondbrain.sync.orchestrator import push as push_records

    oltp = open_unencrypted(db) if no_encryption else open_encrypted(StoreConfig(db_path=db))
    kg = KnowledgeGraph(db_path=db.parent / "kg")
    backend = _sync_backend(folder)
    result = push_records(kg=kg, oltp=oltp, backend=backend)
    click.echo(
        f"pushed: {result.pushed}  policy-skipped: {result.skipped_by_policy}  "
        f"new_cursor: {result.new_cursor}"
    )


@sync.command(name="pull")
@click.argument("folder", type=click.Path(path_type=Path))
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
def sync_pull(folder: Path, db: Path) -> None:
    """Apply any new records waiting in FOLDER to the local KG."""
    from secondbrain.store.kg import KnowledgeGraph
    from secondbrain.sync.orchestrator import pull as pull_records

    kg = KnowledgeGraph(db_path=db.parent / "kg")
    backend = _sync_backend(folder)
    result = pull_records(kg=kg, backend=backend)
    click.echo(f"applied: {result.applied}  rejected: {result.rejected}")


@sync.command(name="status")
@click.argument("folder", type=click.Path(path_type=Path))
def sync_status(folder: Path) -> None:
    """Show backend status (folder, blobs present, peers seen)."""
    backend = _sync_backend(folder)
    import json as _j

    click.echo(_j.dumps(backend.status(), indent=2))


@main.command()
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option(
    "--skip-tcc-probe",
    is_flag=True,
    help="Skip the Screen Recording probe (it spawns the sidecar for 1 frame).",
)
def preflight(db: Path, skip_tcc_probe: bool) -> None:
    """Audit the host: SCK sidecar, TCC, Ollama, embedder cache, Keychain, disk.

    Use this before `secondbrain ui` or `secondbrain run` to learn exactly
    what's missing, with copy-pasteable fixes.
    """
    from secondbrain.preflight import gate, run_preflight

    click.echo("secondbrain preflight\n")
    checks = run_preflight(db, probe_tcc=not skip_tcc_probe)
    for c in checks:
        click.echo(str(c))
    ok, blockers = gate(checks)
    click.echo("")
    if ok:
        click.echo("✓ ready — secondbrain ui will launch the full stack.")
        return
    click.echo(f"✗ {len(blockers)} blocker(s) — fix the items marked ✗ above.")
    raise SystemExit(1)


@main.command(name="install-agent")
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--stub-embedder", is_flag=True, help="Pass --stub-embedder to `run`")
@click.option(
    "--extra-arg",
    "extra_args",
    multiple=True,
    help="Extra argument to pass through to `secondbrain run` (repeatable)",
)
def install_agent(db: Path, stub_embedder: bool, extra_args: tuple[str, ...]) -> None:
    """Install a per-user LaunchAgent so `secondbrain run` starts at login."""
    from secondbrain.launchd import AgentSpec, install, resolve_secondbrain_bin

    bin_path = resolve_secondbrain_bin()
    args = list(extra_args)
    if stub_embedder:
        args.append("--stub-embedder")
    spec = AgentSpec(
        secondbrain_bin=bin_path,
        db_path=db,
        extra_args=tuple(args),
    )
    try:
        path = install(spec)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"installed launchd agent at {path}")
    click.echo("logs: ~/.secondbrain/logs/secondbrain.{out,err}.log")
    click.echo("uninstall: secondbrain uninstall-agent")


@main.command(name="uninstall-agent")
def uninstall_agent_cmd() -> None:
    """Remove the LaunchAgent plist and stop the daemon."""
    from secondbrain.launchd import uninstall

    uninstall()
    click.echo("agent removed")


@main.command(name="agent-status")
def agent_status_cmd() -> None:
    """Report whether the LaunchAgent is installed and loaded."""
    from secondbrain.launchd import status

    s = status()
    click.echo(json.dumps(s, indent=2))


@main.command()
@click.argument("out_path", type=click.Path(path_type=Path))
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
def backup(out_path: Path, db: Path) -> None:
    """Snapshot OLTP + lance + tantivy + kg into a single .tar.gz."""
    from secondbrain import __version__
    from secondbrain.store.backup import make_backup

    manifest = make_backup(db, out_path, secondbrain_version=__version__)
    click.echo(
        f"backup written: {out_path}\n"
        f"  schema_version={manifest.schema_version}\n"
        f"  files={len(manifest.files)}\n"
        f"  created_at={manifest.created_at}"
    )


@main.command()
@click.argument("archive_path", type=click.Path(path_type=Path, exists=True))
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--force", is_flag=True, help="Overwrite existing files in the data root")
def restore(archive_path: Path, db: Path, force: bool) -> None:
    """Restore a backup archive into the data root. Stop the daemon first."""
    from secondbrain.store.backup import restore_backup

    manifest = restore_backup(archive_path, db, force=force)
    click.echo(
        f"restore complete from {archive_path}\n"
        f"  schema_version={manifest.schema_version}\n"
        f"  files={len(manifest.files)}\n"
        f"  archive_created_at={manifest.created_at}"
    )


@main.command(name="run-synthetic")
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--frames", type=int, default=10)
@click.option(
    "--no-encryption",
    is_flag=True,
    help="Open DB unencrypted (dev/tests only)",
)
@click.option("--stub-embedder", is_flag=True)
@click.option(
    "--llm", is_flag=True, help="Route importance + commitments through actants LLM (Ollama)"
)
@click.option("--llm-model", default=None, help="Override the actants LLM model")
@click.option(
    "--redact",
    is_flag=True,
    help="Enable sensitive-content redaction gate (heuristic baseline; "
    "Florence-backed model lands behind the [redact] extra in v0.3)",
)
@click.option(
    "--redact-threshold",
    type=float,
    default=0.6,
    help="Confidence threshold above which a frame is redacted (default 0.6)",
)
def run_synthetic(
    db: Path,
    frames: int,
    no_encryption: bool,
    stub_embedder: bool,
    llm: bool,
    llm_model: str | None,
    redact: bool,
    redact_threshold: float,
) -> None:
    """Drive the cascade with synthetic frames — useful for smoke-testing without a display."""
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(0)

    # Synthetic ax_text crafted so the LLM actually has signal to score.
    samples = [
        "Sam Reed will ship the Snowflake migration by Friday.",
        "Kafka consumer lag spiked at 14:02 on the ingest pipeline.",
        "Stripe billing token expiry hotfix shipped Wednesday afternoon.",
        "Weekend hike notes - golden gate trail conditions are dry.",
        "OpenAI embedding API outage incident review notes attached.",
    ]

    def synth(seed: int) -> Frame:
        arr = rng.integers(0, 255, size=(480, 640, 3), dtype=np.uint8)
        text = samples[seed % len(samples)] if seed % 2 == 0 else None
        return Frame(
            captured_at=now(),
            image=Image.fromarray(arr),
            app_name=f"App{seed % 3}",
            app_bundle_id=f"com.example.app{seed % 3}",
            window_title=f"Window {seed}",
            ax_text=text,
            dirty_rect_fraction=0.5,
        )

    src = SyntheticFrameSource([synth(i) for i in range(frames)])
    cfg = DaemonConfig(
        db_path=db,
        use_encryption=not no_encryption,
        use_stub_embedder=stub_embedder,
        enable_llm=llm,
        llm_model=llm_model,
        enable_redact=redact,
        redact_threshold=redact_threshold,
    )
    daemon = Daemon(cfg)

    async def go() -> None:
        await daemon.run(src)

    asyncio.run(go())
    click.echo(json.dumps(daemon.metrics.as_dict(), indent=2))


if __name__ == "__main__":
    main()
