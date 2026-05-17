"""Live MCP stdio server.

Wraps the in-process tool router (`api/mcp_server.py`) with the MCP SDK's
FastMCP high-level surface so external clients (Claude Desktop, Cursor,
Codex, Windsurf, Gemini CLI) can attach over stdio.

The transport-agnostic tool implementations live in `api/mcp_server.py`
and are unit-tested there; this file is the thin stdio shell.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from secondbrain.api.mcp_server import (
    MCPContext,
    call,
    list_tools,
    make_default_context,
)


def build_app(
    *,
    db: Path,
    use_stub_embedder: bool = False,
    use_encryption: bool = False,
) -> FastMCP:
    """Construct a FastMCP app exposing all 7 SecondBrain tools."""
    ctx: MCPContext = make_default_context(db=db, use_stub_embedder=use_stub_embedder)
    mcp = FastMCP("secondbrain")

    # The architecture's 7 tools. We register them dynamically so the schema
    # in `mcp_server.TOOL_DEFS` stays the source of truth.
    for tdef in list_tools():
        # Closure over `tdef.name` — late binding bites otherwise.
        tool_name = tdef.name

        def _make_handler(_name: str):
            async def handler(args: dict | None = None) -> str:
                """Invoke the in-process router and return JSON text."""
                return json.dumps(call(ctx, _name, args or {}))

            handler.__name__ = "tool_" + _name.replace(".", "_")
            return handler

        mcp.add_tool(
            _make_handler(tool_name),
            name=tool_name,
            description=tdef.description,
        )

    return mcp


def serve(
    *,
    db: Path,
    use_stub_embedder: bool = False,
    use_encryption: bool = False,
) -> None:
    """Run the stdio server. Blocks forever."""
    app = build_app(
        db=db,
        use_stub_embedder=use_stub_embedder,
        use_encryption=use_encryption,
    )
    app.run()  # FastMCP defaults to stdio transport
