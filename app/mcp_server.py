"""MCP server exposing the agent registry over Streamable HTTP.

Mounted into the Flask app at /mcp; lets a leader agent (running inside a
hermes CLI subprocess) call `list_agents` to discover available workers.
"""
from __future__ import annotations

import asyncio
import threading

from mcp.server.fastmcp import FastMCP

from .models.store import store

mcp = FastMCP("hermes-agents", streamable_http_path="/")


@mcp.tool()
def list_agents(role: str | None = None) -> list[dict]:
    """列出当前注册的 agent，可按 role 过滤（'leader' | 'worker'）。"""
    agents = store.snapshot()["agents"]
    if role:
        agents = [a for a in agents if a.get("role") == role]
    return agents


mcp_asgi_app = mcp.streamable_http_app()

# a2wsgi does not dispatch ASGI lifespan events, so FastMCP's session manager
# would never start. Run it in a dedicated background thread with its own loop.
_started = threading.Event()


def _run_session_manager() -> None:
    async def runner() -> None:
        async with mcp.session_manager.run():
            _started.set()
            await asyncio.Event().wait()

    asyncio.run(runner())


def start_session_manager() -> None:
    if _started.is_set():
        return
    threading.Thread(target=_run_session_manager, daemon=True).start()
    _started.wait(timeout=5)
