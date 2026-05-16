"""Federated E2EE sync.

Pluggable backend via the `SyncBackend` protocol. Syncthing is the v0 stopgap
because the encrypted SQLite + age-blob folder pattern is already what the
local DB looks like. Iroh + Automerge land later once iroh-blobs ≥1.0 ships.

The sync layer's *policy* is locked: structured facts + dense embeddings only,
never raw HEVC frames or audio. That contract is enforced by `SyncPolicy`,
not by the backend.
"""
