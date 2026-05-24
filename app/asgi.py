from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.wsgi import WSGIMiddleware
from starlette.routing import Mount, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import create_app
from .mcp_server import mcp_asgi_app
from .middleware import AuthMiddleware, cors_middleware
from .middleware.ratelimit import RateLimitMiddleware
from .models.store import store
from .services.acp import TERMINAL_QUEUE_CLOSE_SENTINEL, pool as session_pool

logger = logging.getLogger("hermes.agent_state")


def _ws_authenticate(websocket: WebSocket) -> bool:
    """Return True if the WebSocket request passes auth, False if it should be rejected."""
    token = os.environ.get("API_TOKEN")
    if not token:
        return True
    provided = (
        websocket.headers.get("X-API-Key")
        or websocket.query_params.get("token")
        or ""
    )
    auth_header = websocket.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        provided = provided or auth_header[7:]
    if not provided or provided != token:
        return False
    return True


async def terminal_ws(websocket: WebSocket) -> None:
    agent_id = websocket.path_params["agent_id"]

    if not _ws_authenticate(websocket):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    logger.info("[terminal-ws] accept agent=%s", agent_id)

    agent = store.find_agent(agent_id)
    if agent is None:
        await websocket.send_json(
            {"type": "status", "status": "error", "message": "agent not found"}
        )
        logger.info("[terminal-ws] missing agent=%s", agent_id)
        await websocket.close(code=4404)
        return

    try:
        subscriber, state = session_pool.attach_terminal(agent_id)
    except RuntimeError as exc:
        await websocket.send_json(
            {"type": "status", "status": "not_running", "message": str(exc)}
        )
        logger.info("[terminal-ws] attach failed agent=%s error=%s", agent_id, exc)
        await websocket.close(code=4409)
        return

    async def pump_terminal_output() -> None:
        while True:
            message = await asyncio.to_thread(subscriber.get)
            if message == TERMINAL_QUEUE_CLOSE_SENTINEL:
                logger.info("[terminal-ws] close sentinel agent=%s", agent_id)
                return
            await websocket.send_json(message)
            if message.get("type") != "output":
                logger.info("[terminal-ws] send agent=%s type=%s", agent_id, message.get("type"))
            if message.get("type") == "status":
                return

    try:
        await websocket.send_json(
            {
                "type": "ready",
                "rows": state["rows"],
                "cols": state["cols"],
                "snapshot_text": state["snapshot_text"],
                "snapshot_ansi": state["snapshot_ansi"],
            }
        )
        logger.info(
            "[terminal-ws] ready agent=%s rows=%s cols=%s",
            agent_id, state["rows"], state["cols"],
        )

        output_task = asyncio.create_task(pump_terminal_output())
        while True:
            receive_task = asyncio.create_task(websocket.receive_json())
            done, pending = await asyncio.wait(
                {output_task, receive_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receive_task in pending:
                receive_task.cancel()
                with suppress(asyncio.CancelledError):
                    await receive_task
            if output_task in done:
                with suppress(asyncio.CancelledError):
                    await output_task
                break
            payload = receive_task.result()
            message_type = payload.get("type")
            if message_type == "input":
                logger.info(
                    "[terminal-ws] input agent=%s bytes=%s",
                    agent_id, len(str(payload.get("data") or "")),
                )
                session_pool.send_terminal_data(agent_id, str(payload.get("data") or ""))
                continue
            if message_type == "resize":
                logger.info(
                    "[terminal-ws] resize agent=%s rows=%s cols=%s",
                    agent_id, payload.get("rows"), payload.get("cols"),
                )
                session_pool.resize_terminal(
                    agent_id,
                    int(payload.get("rows") or 0),
                    int(payload.get("cols") or 0),
                )
                continue
            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("[terminal-ws] disconnect agent=%s", agent_id)
    finally:
        session_pool.detach_terminal(agent_id, subscriber)
        if "output_task" in locals():
            output_task.cancel()
            with suppress(asyncio.CancelledError):
                await output_task


def create_asgi_app() -> Starlette:
    flask_app = create_app()
    starlette = Starlette(
        routes=[
            WebSocketRoute("/api/agents/{agent_id:str}/terminal/ws", terminal_ws),
            Mount("/mcp", app=mcp_asgi_app),
            Mount("/", app=WSGIMiddleware(flask_app)),
        ],
        middleware=[
            Middleware(RateLimitMiddleware),
            Middleware(AuthMiddleware),
        ],
    )
    starlette = cors_middleware(starlette)
    return starlette
