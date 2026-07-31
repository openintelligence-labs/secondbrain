# Security policy

SecondBrain continuously captures screen contents, browser activity, and documents, then stores them in an encrypted local index. The data it holds is among the most sensitive on a user's machine. We treat security reports accordingly.

## Reporting a vulnerability

If you find a security issue — in the capture daemon, the Swift sidecars, the encrypted stores, the MCP server, the sync/pairing layer, or the compliance path — please **do not open a public issue**.

File a private report through GitHub Security Advisories:

> **<https://github.com/openintelligence-labs/secondbrain/security/advisories/new>**

Include:

1. The component affected (e.g. "MCP server", "SQLCipher store", "deny-list", "X25519 pairing").
2. A reproduction case — minimal steps that demonstrate the issue.
3. The impact you've observed or believe is possible.
4. Whether you've already disclosed the issue elsewhere.

We aim to acknowledge within 48 hours and to publish a fix (or a detailed mitigation) within 30 days. For anything that causes captured data to leave the device, we will cut an emergency release rather than wait for the next scheduled one.

## Supported versions

| Version | Status |
|---|---|
| 0.3.x (current) | Supported. Fixes land in the latest patch. |
| < 0.3 | Unsupported. Please upgrade. |

## Scope

**In scope — and treated as high severity:**

- **Any unintended egress of captured data.** Captures, OCR text, embeddings, the knowledge graph, and the audit log are supposed to stay on the device. A path that sends any of it anywhere other than the LLM provider the user explicitly configured is the most serious bug this project can have.
- **Deny-list bypass** — capture of an app, window, or URL the user excluded.
- **Encryption failures** — plaintext capture content, OCR text, or embeddings written outside the encrypted stores; keys written to disk in the clear; a database left decrypted at rest.
- **Key handling** — encryption keys or provider API keys leaking into logs, traces, crash reports, or the audit log.
- **`memory.forget` not actually forgetting** — data surviving a GDPR Art. 17 deletion in any store (OLTP, LanceDB, tantivy, Kùzu, or on-disk artifacts).
- **Air-gap mode failing to suppress network egress.**
- **MCP server flaws** allowing a connected client to read captures beyond the requested scope, escape the query interface, or mutate the filesystem.
- **Pairing/sync flaws** — X25519 pairing accepting an unauthenticated peer, or sync transmitting more than the sync policy allows.
- Privilege escalation or sandbox escape via the Swift capture sidecars.
- Path traversal or arbitrary file read/write through the CLI, importers, or wearable ingest path.

**Out of scope** (working as designed):

- SecondBrain capturing your screen after you granted it screen-recording permission and started the daemon. That is the product.
- Prompted text reaching a hosted LLM provider you deliberately configured. The default is local Ollama; choosing a hosted provider is an explicit opt-in with a documented data flow.
- Another process on your machine reading your data while the daemon is unlocked and running. SecondBrain protects data at rest, not against a local attacker who already has your user session.
- Model output being wrong in a digest or person card.

## Data flow

SecondBrain is **local-by-default, BYO-LLM**. Captures, embeddings, the knowledge graph, and the audit log never leave the device. The single configurable egress is the LLM transport, which defaults to a local Ollama endpoint and makes no off-device request in that configuration. If you point it at a hosted provider, only the prompted text egresses, and only because you opted in.

There is no telemetry, no analytics, and no opt-out toggle for either — because there is nothing to opt out of. An outbound request to any host you did not configure is a security bug, and we want to hear about it immediately.
