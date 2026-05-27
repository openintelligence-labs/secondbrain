"""Audit-log integration for the redaction gate (spec redaction-v0 §6.1).

Proves the privacy invariant: when a frame is redacted, exactly one audit
row lands in the OLTP audit_log table, and that row contains zero
recoverable sensitive content (no image bytes, no original window title,
no AX text). The user can later run `secondbrain compliance audit` and
prove that frames were refused at specific times — without re-leaking
what those frames showed.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import numpy as np
from PIL import Image

from secondbrain.capture.capability import CapabilityCache
from secondbrain.capture.dedup import DedupCascade
from secondbrain.capture.deny_list import DenyList
from secondbrain.capture.frame import Frame
from secondbrain.capture.pipeline import CapturePipeline
from secondbrain.compliance.audit import AuditLog
from secondbrain.compliance.sensitive import SensitiveDecision
from secondbrain.store.oltp import SCHEMA_MIGRATIONS


def _conn() -> sqlite3.Connection:
    """An in-memory OLTP DB with the daemon's schema applied."""
    c = sqlite3.connect(":memory:")
    for _version, sql in SCHEMA_MIGRATIONS:
        c.executescript(sql)
    return c


def _img(seed: int = 0) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8))


def _frame(image: Image.Image, app: str = "Safari", title: str = "Login — Bank") -> Frame:
    return Frame(
        captured_at=datetime.now(UTC),
        image=image,
        app_name=app,
        app_bundle_id="com.apple.Safari",
        window_title=title,
        dirty_rect_fraction=1.0,
    )


class _AlwaysSensitive:
    def classify(self, image, *, hint="", timeout_ms=250) -> SensitiveDecision:
        return SensitiveDecision(
            is_sensitive=True,
            confidence=0.91,
            categories=["password_field"],
            model="test-always-sensitive",
            latency_ms=142,
        )


class _NeverSensitive:
    def classify(self, image, *, hint="", timeout_ms=250) -> SensitiveDecision:
        return SensitiveDecision(is_sensitive=False, confidence=0.1, model="test-never")


def _pipeline(conn, *, classifier, audit: AuditLog | None) -> CapturePipeline:
    return CapturePipeline(
        deny=DenyList.from_defaults(),
        cascade=DedupCascade(classifier=classifier, redact_threshold=0.6),
        capability=CapabilityCache(conn),
        conn=conn,
        audit=audit,
    )


# --- spec §6.1: a redacted frame writes one audit row -------------------


def test_redacted_frame_writes_one_audit_row():
    conn = _conn()
    audit = AuditLog(conn)
    pipe = _pipeline(conn, classifier=_AlwaysSensitive(), audit=audit)

    result = pipe.process_one(_frame(_img(1)))

    assert result is None, "redacted frame must not return a Capture"
    rows = list(conn.execute("SELECT action, actor, detail_json FROM audit_log"))
    assert len(rows) == 1
    action, actor, detail_json = rows[0]
    assert action == "capture.redacted"
    assert actor == "daemon"

    detail = json.loads(detail_json)
    assert detail["categories"] == ["password_field"]
    assert detail["confidence"] == 0.91
    assert detail["model"] == "test-always-sensitive"
    assert detail["latency_ms"] == 142
    assert detail["app_name"] == "Safari"
    assert detail["app_bundle_id"] == "com.apple.Safari"
    assert "captured_at" in detail


# --- spec §6.1: no sensitive content leaks into the audit row -----------


def test_redaction_audit_row_carries_no_sensitive_content():
    """The audit row must NEVER contain the original window title, AX text,
    image bytes, or anything that would re-leak the redacted content."""
    conn = _conn()
    audit = AuditLog(conn)
    pipe = _pipeline(conn, classifier=_AlwaysSensitive(), audit=audit)

    secret_title = "BankOfAmerica — Account 4111111111111111"
    secret_ax = "Password: hunter2"
    frame = Frame(
        captured_at=datetime.now(UTC),
        image=_img(1),
        app_name="Safari",
        app_bundle_id="com.apple.Safari",
        window_title=secret_title,
        ax_text=secret_ax,
        dirty_rect_fraction=1.0,
    )
    pipe.process_one(frame)

    rows = list(conn.execute("SELECT actor, action, query, cited_json, detail_json FROM audit_log"))
    assert len(rows) == 1
    blob = json.dumps(rows[0])
    assert secret_title not in blob
    assert "4111111111111111" not in blob
    assert secret_ax not in blob
    assert "hunter2" not in blob


# --- contract: non-redacted paths do not pollute the audit log ----------


def test_persisted_frame_writes_no_audit_row():
    conn = _conn()
    audit = AuditLog(conn)
    pipe = _pipeline(conn, classifier=_NeverSensitive(), audit=audit)

    capture = pipe.process_one(_frame(_img(1)))

    assert capture is not None, "frame should persist when classifier clears it"
    rows = list(conn.execute("SELECT COUNT(1) FROM audit_log"))
    assert rows[0][0] == 0


def test_classifier_disabled_writes_no_audit_row():
    """A daemon running without redaction wired in must not touch the
    audit log from the capture path at all."""
    conn = _conn()
    audit = AuditLog(conn)
    pipe = _pipeline(conn, classifier=None, audit=audit)

    pipe.process_one(_frame(_img(1)))

    rows = list(conn.execute("SELECT COUNT(1) FROM audit_log"))
    assert rows[0][0] == 0


# --- contract: missing audit log is not a crash -------------------------


def test_redaction_without_audit_log_does_not_crash():
    """A pipeline with audit=None still redacts correctly — the audit-log
    write is skipped, but the gate still drops the frame."""
    conn = _conn()
    pipe = _pipeline(conn, classifier=_AlwaysSensitive(), audit=None)

    result = pipe.process_one(_frame(_img(1)))

    assert result is None
    # Metrics still recorded.
    assert pipe.metrics.by_gate.get("redacted") == 1


# --- spec §6.1: signed export round-trips the redaction event -----------


def test_signed_export_includes_redaction_event():
    """The user's GDPR Art. 30 export must include the redaction trail so
    they can prove what was refused."""
    conn = _conn()
    audit = AuditLog(conn)
    pipe = _pipeline(conn, classifier=_AlwaysSensitive(), audit=audit)
    pipe.process_one(_frame(_img(1)))
    pipe.process_one(_frame(_img(2)))

    bundle = audit.export_signed(signing_key32=b"\x00" * 32)
    assert bundle["schema"] == "secondbrain.audit.v1"
    actions = [e["action"] for e in bundle["entries"]]
    assert actions == ["capture.redacted", "capture.redacted"]
    # HMAC signature is present and non-trivial.
    assert len(bundle["signature_hmac_sha256"]) == 64
