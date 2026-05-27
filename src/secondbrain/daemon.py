"""SecondBrain capture daemon (capture + memory wiring).

A long-running asyncio process that:

    1. Opens the encrypted OLTP store.
    2. Wires the cascade (deny-list, AX-hash, dHash/pHash/SSIM, capability cache).
    3. Drives a `FrameSource` and persists what survives the cascade.
    4. (optional) For each persisted capture, runs the memory pipeline:
       chunk → embed → LanceDB + tantivy + Kùzu KG (with A-MEM linking).

The daemon does not own a frame source itself — callers (CLI / tests) inject
one. That keeps the daemon trivially testable end-to-end without a display.
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from secondbrain.capture.capability import CapabilityCache
from secondbrain.capture.dedup import DedupCascade
from secondbrain.capture.deny_list import DenyList
from secondbrain.capture.frame import FrameSource
from secondbrain.capture.pipeline import CapturePipeline, CascadeMetrics
from secondbrain.embed.text import TextEmbedder
from secondbrain.indexing import Indexer
from secondbrain.memory.amem import AMemLinker
from secondbrain.memory.entities import EntityResolver
from secondbrain.memory.pipeline import MemoryPipeline
from secondbrain.store.kg import KnowledgeGraph
from secondbrain.store.oltp import StoreConfig, open_encrypted, open_unencrypted
from secondbrain.store.text_index import TextIndex
from secondbrain.store.vector import VectorStore

log = structlog.get_logger()


@dataclass
class DaemonConfig:
    db_path: Path
    deny_list_yaml: Path | None = None
    use_encryption: bool = True
    keyring_service: str = "secondbrain.device_root_key"
    keyring_user: str = "default"
    metrics: CascadeMetrics = field(default_factory=CascadeMetrics)
    # Set to False in tests / sandboxed CI to avoid the embedder model load.
    enable_memory: bool = True
    # Stub embedder skips the multi-GB Nomic v2 download — useful for smoke tests.
    use_stub_embedder: bool = False
    # Visual embeddings (ColQwen2.5) are expensive (~3.3s/image on M-series).
    # Off by default; turn on once `--visual` is requested.
    enable_visual: bool = False
    # When True, captures with empty AX text fall through to Apple Vision OCR
    # (free, ANE-accelerated, ~80–150ms/frame on M-series). Off by default
    # because tests run images that aren't text and OCR would still try.
    enable_ocr_fallback: bool = False
    # When True, importance scoring + commitment extraction + digest synthesis
    # all route through actants.LLM.* (Ollama default). Each call falls back
    # to its heuristic on timeout/error so a flaky LLM never blocks ingest.
    enable_llm: bool = False
    # Optional model override for the actants LLM path (importance + commitment
    # extraction). None → actants picks its default model.
    llm_model: str | None = None
    # When True, embeddings also route through actants (default `nomic-embed-text`
    # via Ollama). False keeps the local sentence-transformers Nomic v2 path.
    llm_embeddings: bool = False
    llm_embedding_model: str | None = None
    # Sensitive-content redaction gate. False keeps the daemon's existing
    # behavior (no classifier wired). True attaches a classifier — today the
    # heuristic baseline; the Florence-backed implementation lands behind the
    # [redact] extra in a follow-up PR.
    enable_redact: bool = False
    redact_threshold: float = 0.6


class Daemon:
    def __init__(self, cfg: DaemonConfig) -> None:
        self.cfg = cfg
        self._stop = asyncio.Event()
        self._pipeline: CapturePipeline | None = None
        self._memory: MemoryPipeline | None = None
        self._indexer: Indexer | None = None
        self._visual = None  # VisualEmbedder | None
        self._visual_store = None  # VisualStore | None

    def _open_conn(self):
        if self.cfg.use_encryption:
            return open_encrypted(
                StoreConfig(
                    db_path=self.cfg.db_path,
                    keyring_service=self.cfg.keyring_service,
                    keyring_user=self.cfg.keyring_user,
                )
            )
        return open_unencrypted(self.cfg.db_path)

    def _build_memory_layer(self):
        """Stand up KG + vector + tantivy + memory pipeline.

        Layout:
            <db_path>                — OLTP (encrypted SQLite)
            <db_path>.parent/lance/  — LanceDB chunks
            <db_path>.parent/tantivy/— BM25 index
            <db_path>.parent/kg/     — Kùzu graph
        """
        base = self.cfg.db_path.parent
        if self.cfg.use_stub_embedder:
            from secondbrain.embed.stub import StubEmbedder

            embedder = StubEmbedder()
        elif self.cfg.llm_embeddings:
            embedder = TextEmbedder.via_actants(
                model=self.cfg.llm_embedding_model or "nomic-embed-text",
            )
        else:
            embedder = TextEmbedder()

        # Flip the LLM swap-in points if requested. Honor SECONDBRAIN_LLM_*
        # env vars (BYO-LLM contract) by mirroring them into actants's
        # ACTANTS_* settings before any LLM client is constructed.
        if self.cfg.enable_llm:
            from secondbrain.llm_config import apply_to_actants_env, from_env
            from secondbrain.memory.commitments import use_actants_extractor
            from secondbrain.memory.digest import use_actants_synthesizer
            from secondbrain.memory.importance import use_actants_scorer

            llm_cfg = from_env()
            apply_to_actants_env(llm_cfg)

            # CLI `--llm-model` takes precedence over env. Otherwise let actants
            # pick its env-driven default.
            model = self.cfg.llm_model or llm_cfg.model

            use_actants_scorer(model=model)
            use_actants_extractor(model=model)
            use_actants_synthesizer(model=model)
            log.info(
                "daemon.llm_enabled",
                model=model or "(actants env default)",
                config=llm_cfg.describe(),
            )

        vector = VectorStore(db_path=base / "lance")
        text = TextIndex(index_path=base / "tantivy")
        kg = KnowledgeGraph(db_path=base / "kg")

        self._indexer = Indexer(embedder=embedder, vector=vector, text=text)
        self._memory = MemoryPipeline(
            kg=kg,
            linker=AMemLinker(embedder=embedder),
            resolver=EntityResolver(kg=kg),
        )

        if self.cfg.enable_visual:
            from secondbrain.embed.visual import VisualEmbedder
            from secondbrain.store.visual import VisualStore

            self._visual = VisualEmbedder()
            self._visual_store = VisualStore(db_path=base / "lance_visual")

    def build_pipeline(self) -> CapturePipeline:
        conn = self._open_conn()
        self._oltp_conn = conn
        deny = (
            DenyList.from_yaml(self.cfg.deny_list_yaml)
            if self.cfg.deny_list_yaml
            else DenyList.from_defaults()
        )
        classifier = None
        if self.cfg.enable_redact:
            from secondbrain.compliance.sensitive import get_classifier

            classifier = get_classifier()
        cascade = DedupCascade(
            classifier=classifier,
            redact_threshold=self.cfg.redact_threshold,
        )
        capability = CapabilityCache(conn)
        pipeline = CapturePipeline(
            deny=deny,
            cascade=cascade,
            capability=capability,
            conn=conn,
            metrics=self.cfg.metrics,
        )
        self._pipeline = pipeline
        if self.cfg.enable_memory:
            self._build_memory_layer()
        return pipeline

    def mcp_context(self):
        """Return an MCPContext that shares this daemon's handles.

        Tantivy + LanceDB + Kùzu all hold exclusive process-wide locks on
        their on-disk indices, so the gateway MUST reuse the daemon's open
        instances instead of opening its own. Call after `build_pipeline()`.
        """
        from secondbrain.api.mcp_server import MCPContext

        if self._pipeline is None or self._indexer is None or self._memory is None:
            raise RuntimeError(
                "Daemon.build_pipeline() must run before mcp_context() — "
                "enable_memory must also be True."
            )
        return MCPContext(
            kg=self._memory.kg,
            vector=self._indexer.vector,
            text=self._indexer.text,
            embedder=self._indexer.embedder,
            oltp=self._oltp_conn,
            oltp_path=self.cfg.db_path,
        )

    @property
    def metrics(self) -> CascadeMetrics:
        return self.cfg.metrics

    def stop(self) -> None:
        self._stop.set()

    async def run(self, source: FrameSource) -> None:
        """Drive a frame source through the cascade until stop is requested."""
        if self._pipeline is None:
            self.build_pipeline()
        assert self._pipeline is not None

        log.info(
            "daemon.start",
            db=str(self.cfg.db_path),
            memory_enabled=self.cfg.enable_memory,
            stub_embedder=self.cfg.use_stub_embedder,
        )
        # Signal handlers can only be installed on the main thread of the
        # main interpreter. The `secondbrain ui` shell runs us on a worker
        # thread, where this would raise ValueError — swallow it; the UI
        # uses daemon.stop() explicitly on quit.
        import threading

        if threading.current_thread() is threading.main_thread():
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                with suppress(NotImplementedError, ValueError):
                    loop.add_signal_handler(sig, self.stop)

        async def consume() -> None:
            async for capture in self._pipeline.run(source):
                if capture is None:
                    continue
                log.debug(
                    "capture.persisted",
                    id=capture.id,
                    app=capture.app_name,
                )
                # OCR fallback when AX text is empty.
                # We accept two sources: an on-disk `pixel_path` (HEIC mode)
                # OR the in-memory PIL image the capture pipeline stashes for
                # the visual encoder (PNG/inline mode). The latter case is
                # the production path on macOS — without it Cursor / Slack /
                # Electron captures would never get text.
                if self.cfg.enable_ocr_fallback and not capture.ax_text:
                    try:
                        from secondbrain.capture.pipeline import _IMAGE_FOR_VISUAL
                        from secondbrain.ocr.selector import aselect_text

                        ocr_path = capture.pixel_path
                        tmp_path = None
                        if ocr_path is None:
                            img = _IMAGE_FOR_VISUAL.get(capture.id)
                            if img is not None:
                                import tempfile

                                # delete=False: the path outlives this block and
                                # is cleaned up downstream via tmp_path.
                                tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
                                    suffix=".png", delete=False
                                )
                                img.save(tmp.name, format="PNG")
                                tmp.close()
                                ocr_path = Path(tmp.name)
                                tmp_path = ocr_path
                        if ocr_path is not None:
                            outcome = await aselect_text(ax_text=None, image_path=ocr_path)
                            if outcome.text and outcome.provider != "none":
                                capture.ocr_text = outcome.text
                                log.debug(
                                    "ocr.fallback_used",
                                    provider=outcome.provider,
                                    conf=outcome.confidence,
                                    capture_id=capture.id,
                                    chars=len(outcome.text),
                                )
                        if tmp_path is not None and tmp_path.exists():
                            tmp_path.unlink()
                    except Exception as e:
                        log.warning("ocr.fallback_failed", err=repr(e))

                if self._indexer is not None:
                    try:
                        n = self._indexer.index_capture(capture)
                        if n > 0 and self._memory is not None:
                            self._memory.ingest(capture)
                    except Exception as e:
                        log.warning("memory.ingest_failed", capture_id=capture.id, err=repr(e))
                if (
                    self._visual is not None
                    and self._visual_store is not None
                    and capture.gate == "persist"
                ):
                    from secondbrain.capture.pipeline import take_image_for_visual

                    img = take_image_for_visual(capture.id)
                    if img is not None:
                        try:
                            patches = await asyncio.to_thread(self._encode_visual, img)
                            if patches is not None:
                                self._visual_store.add(
                                    capture.id,
                                    patches,
                                    created_at=capture.captured_at.timestamp(),
                                )
                        except Exception as e:
                            log.warning(
                                "visual.embed_failed",
                                capture_id=capture.id,
                                err=repr(e),
                            )
                else:
                    # Drain the sidecar to avoid leaking PIL images when visual is off.
                    from secondbrain.capture.pipeline import take_image_for_visual

                    take_image_for_visual(capture.id)

        consumer = asyncio.create_task(consume())
        try:
            await asyncio.wait(
                [consumer, asyncio.create_task(self._stop.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            consumer.cancel()
            with suppress(asyncio.CancelledError):
                await consumer
            await source.close()
            log.info("daemon.stop", metrics=self.metrics.as_dict())

    def _encode_visual(self, image):
        """Encode a single image with ColQwen2.5; reduce to a (P, 128) numpy
        array suitable for `VisualStore.add`. Heavy, runs in a thread."""
        import numpy as np

        out = self._visual.embed_images([image])
        # out is (1, P, dim) torch.Tensor on whatever device the embedder used
        try:
            arr = out[0].detach().to("cpu").float().numpy()
        except AttributeError:
            arr = np.asarray(out)[0]
        # Normalize patches so MaxSim with normalized queries is bounded.
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (arr / norms).astype("float32")
