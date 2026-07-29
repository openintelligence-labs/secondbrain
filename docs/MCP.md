# SecondBrain MCP integration

SecondBrain exposes 7 named tools through the Model Context Protocol so any
MCP-aware client can attach to your memory in one click.

## Tools

| Name | Purpose |
|---|---|
| `memory.search` | Hybrid (BM25 ⊕ dense → RRF k=60) retrieval over your captures. |
| `memory.recall_timeline` | Bi-temporal "what happened between X and Y?" |
| `memory.get_person` | Person card across modalities (Slack/calendar/screen). |
| `memory.commitments` | Open / done / cancelled / broken commitments. |
| `memory.daily_digest` | The morning "yesterday → today" card. |
| `memory.add_note` | Inject an explicit user note into the graph. |
| `memory.forget` | **GDPR Art. 17 cascading delete + audit-log write.** |

Every call is logged to the SecondBrain audit log. Export the signed log with
`secondbrain compliance audit`.

## Client recipes

### Claude Desktop / Claude Code

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "secondbrain": {
      "command": "secondbrain",
      "args": ["mcp"]
    }
  }
}
```

### Cursor

`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "secondbrain": { "command": "secondbrain", "args": ["mcp"] }
  }
}
```

### Codex CLI

```bash
codex --mcp secondbrain=secondbrain mcp
```

### Windsurf

Settings → MCP Servers → Add → Command: `secondbrain mcp`.

### Gemini CLI

```bash
gemini --mcp-server "secondbrain mcp"
```

## Transport

- **stdio** is the default for local clients (Claude Desktop, Cursor).
- **Streamable HTTP** is available with `secondbrain mcp --http --port 7821`
  and binds to 127.0.0.1 with Origin validation (DNS-rebinding defense).
- OAuth 2.1 PKCE Resource-Server pattern engages automatically for any
  non-localhost request.
