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
def list_workers() -> list[dict]:
    """列出当前注册的所有 worker agent（供 leader 进行任务分派时发现下属）。

    返回的字段包含 agent_id / name / description / status / current_task / load，
    不包含 leader 自身，避免 leader 把任务派给自己。
    """
    return [
        a for a in store.snapshot()["agents"] if a.get("role") == "worker"
    ]


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
