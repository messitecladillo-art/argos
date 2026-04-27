from __future__ import annotations

import asyncio
from contextlib import suppress

from starlette.applications import Starlette
from starlette.middleware.wsgi import WSGIMiddleware
from starlette.routing import Mount, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import create_app
from .mcp_server import mcp_asgi_app
from .models.store import store
from .services.acp import TERMINAL_QUEUE_CLOSE_SENTINEL, pool as session_pool


async def terminal_ws(websocket: WebSocket) -> None:
    agent_id = websocket.path_params["agent_id"]
    await websocket.accept()

    agent = store.find_agent(agent_id)
    if agent is None:
        await websocket.send_json(
            {"type": "status", "status": "error", "message": "agent not found"}
        )
        await websocket.close(code=4404)
        return

    try:
        subscriber, state = session_pool.attach_terminal(agent_id)
    except RuntimeError as exc:
        await websocket.send_json(
            {"type": "status", "status": "not_running", "message": str(exc)}
        )
        await websocket.close(code=4409)
        return

    async def pump_terminal_output() -> None:
        while True:
            message = await asyncio.to_thread(subscriber.get)
            if message == TERMINAL_QUEUE_CLOSE_SENTINEL:
                return
            await websocket.send_json(message)
            if message.get("type") == "status":
                return

    try:
        await websocket.send_json(
            {
                "type": "ready",
                "rows": state["rows"],
                "cols": state["cols"],
            }
        )
        for chunk in state["buffer"]:
            await websocket.send_json({"type": "output", "data": chunk})

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
                session_pool.send_terminal_data(agent_id, str(payload.get("data") or ""))
                continue
            if message_type == "resize":
                session_pool.resize_terminal(
                    agent_id,
                    int(payload.get("rows") or 0),
                    int(payload.get("cols") or 0),
                )
                continue
            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        session_pool.detach_terminal(agent_id, subscriber)
        if "output_task" in locals():
            output_task.cancel()
            with suppress(asyncio.CancelledError):
                await output_task


def create_asgi_app() -> Starlette:
    flask_app = create_app()
    return Starlette(
        routes=[
            WebSocketRoute("/api/agents/{agent_id:str}/terminal/ws", terminal_ws),
            Mount("/mcp", app=mcp_asgi_app),
            Mount("/", app=WSGIMiddleware(flask_app)),
        ]
    )
