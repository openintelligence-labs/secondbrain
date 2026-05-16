from __future__ import annotations

from secondbrain.sync.backend import InMemoryBackend
from secondbrain.sync.pairing import DeviceIdentity, derive_shared_key
from secondbrain.sync.policy import DeviceClass, SyncPolicy


def test_policy_default_allows_facts_blocks_frames():
    p = SyncPolicy()
    assert p.should_sync("memory_node") is True
    assert p.should_sync("dense_embedding") is True
    assert p.should_sync("hevc_frame") is False
    assert p.should_sync("audio_chunk") is False


def test_policy_regulated_blocks_everything():
    p = SyncPolicy(device_class=DeviceClass.REGULATED)
    assert p.should_sync("memory_node") is False
    assert p.should_sync("kg_edge") is False


def test_policy_extra_deny_overrides_default_allow():
    p = SyncPolicy(extra_deny={"memory_node"})
    assert p.should_sync("memory_node") is False
    assert p.should_sync("kg_edge") is True


def test_in_memory_backend_round_trips():
    a = InMemoryBackend(name="A")
    b = InMemoryBackend(name="B")
    a.push("memory_node", {"id": "m1", "content": "hi"})
    a.deliver_to_peer(b)
    received = b.pull()
    assert received == [("memory_node", {"id": "m1", "content": "hi"})]


def test_pairing_x25519_dh_produces_shared_secret():
    a = DeviceIdentity.fresh()
    b = DeviceIdentity.fresh()
    s_ab = derive_shared_key(a.private_key, b.public_key_bytes)
    s_ba = derive_shared_key(b.private_key, a.public_key_bytes)
    assert s_ab == s_ba
    assert len(s_ab) == 32


def test_fingerprint_words_are_stable():
    a = DeviceIdentity.fresh()
    assert len(a.fingerprint_words()) == 6
    assert a.fingerprint_words() == a.fingerprint_words()
    assert len(a.fingerprint_hex()) == 16
