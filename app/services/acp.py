"""Per-agent persistent `hermes -p <profile> acp` subprocess pool.

Each ACPClient owns one hermes acp subprocess with a live session. Prompts
are non-blocking: text goes in via stdin, chunks stream back through a
reader thread that pushes events to the store, and on_final fires once the
JSON-RPC response for the prompt arrives with a stopReason.
"""
from __future__ import annotations

import itertools
import json
import os
import subprocess
import threading
from typing import Callable

from ..models.store import store


ACP_PROTOCOL_VERSION = 1


class ACPClient:
    def __init__(
        self,
        profile_name: str,
        agent_id: str,
        on_final: Callable[[str, str], None],
    ) -> None:
        self.profile_name = profile_name
        self.agent_id = agent_id
        self.on_final = on_final
        self.proc = subprocess.Popen(
            ["hermes", "-p", profile_name, "acp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

        self._write_lock = threading.Lock()
        self._id_counter = itertools.count(1)
        self._session_id: str | None = None
        self._session_ready = threading.Event()
        self._pending_prompt_id: int | None = None
        self._message_buffer: list[str] = []
        self._closed = False
        self._on_crash_done = False

        threading.Thread(target=self._reader_loop, daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

        init_id = self._next_id()
        self._send({
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                },
            },
        })
        # session/new is sent eagerly; sessionId arrives async via reader loop
        new_id = self._next_id()
        self._session_new_id = new_id
        self._send({
            "jsonrpc": "2.0",
            "id": new_id,
            "method": "session/new",
            "params": {"cwd": os.getcwd(), "mcpServers": []},
        })

    # ------------------------------------------------------------------ io
    def _next_id(self) -> int:
        return next(self._id_counter)

    def _send(self, obj: dict) -> None:
        if self._closed or self.proc.stdin is None:
            return
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        with self._write_lock:
            try:
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                self._mark_crashed("stdin closed")

    def _reader_loop(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                self._handle(msg)
            except Exception as exc:  # noqa: BLE001 - reader must survive
                store.push_event(
                    "agent.acp.failed",
                    self.agent_id,
                    None,
                    {"text": f"ACP handle error: {exc}"},
                )
        self._mark_crashed("stdout closed")

    def _stderr_loop(self) -> None:
        assert self.proc.stderr is not None
        for _ in self.proc.stderr:
            pass  # drain; hermes logs here, not protocol data

    def _handle(self, msg: dict) -> None:
        # notifications: session/update
        if msg.get("method") == "session/update":
            update = (msg.get("params") or {}).get("update") or {}
            kind = update.get("sessionUpdate")
            content = update.get("content")
            text = ""
            if isinstance(content, dict):
                text = content.get("text") or ""
            elif isinstance(content, list):
                text = "".join(
                    (part.get("text") or "")
                    for part in content
                    if isinstance(part, dict)
                )
            if kind == "agent_message_chunk" and text:
                self._message_buffer.append(text)
                store.push_event(
                    "agent.output.chunk",
                    self.agent_id,
                    None,
                    {"text": text},
                )
            return

        # responses
        if "id" in msg and ("result" in msg or "error" in msg):
            mid = msg["id"]
            if mid == self._session_new_id and "result" in msg:
                self._session_id = (msg["result"] or {}).get("sessionId")
                if self._session_id:
                    self._session_ready.set()
                return
            if self._pending_prompt_id is not None and mid == self._pending_prompt_id:
                reply = "".join(self._message_buffer).strip()
                self._message_buffer = []
                self._pending_prompt_id = None
                try:
                    self.on_final(self.agent_id, reply)
                except Exception as exc:  # noqa: BLE001
                    store.push_event(
                        "agent.output.failed",
                        self.agent_id,
                        None,
                        {"text": f"on_final handler error: {exc}"},
                    )
                return

    # ------------------------------------------------------------------ api
    def prompt(self, text: str, timeout: float = 10.0) -> None:
        if not self._session_ready.wait(timeout=timeout):
            raise RuntimeError("ACP session not ready")
        if self._pending_prompt_id is not None:
            raise RuntimeError("previous prompt still running")
        self._message_buffer = []
        pid = self._next_id()
        self._pending_prompt_id = pid
        self._send({
            "jsonrpc": "2.0",
            "id": pid,
            "method": "session/prompt",
            "params": {
                "sessionId": self._session_id,
                "prompt": [{"type": "text", "text": text}],
            },
        })

    def _mark_crashed(self, reason: str) -> None:
        if self._on_crash_done:
            return
        self._on_crash_done = True
        if self._closed:
            return
        store.update_agent(self.agent_id, acp_status="crashed", status="offline")
        store.push_event(
            "agent.acp.failed",
            self.agent_id,
            None,
            {"text": f"ACP subprocess ended: {reason}"},
        )

    def close(self) -> None:
        self._closed = True
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


class ACPPool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.clients: dict[str, ACPClient] = {}
        # worker_agent_id -> leader_agent_id waiting for the reply
        self.pending_reply_to: dict[str, str] = {}

    def is_running(self, agent_id: str) -> bool:
        with self._lock:
            return agent_id in self.clients

    def start(self, agent: dict) -> bool:
        agent_id = agent["agent_id"]
        profile_name = agent["profile_name"]
        with self._lock:
            if agent_id in self.clients:
                return True
        try:
            client = ACPClient(profile_name, agent_id, self._on_final)
        except FileNotFoundError:
            store.update_agent(agent_id, acp_status="crashed")
            store.push_event(
                "agent.acp.failed",
                agent_id,
                None,
                {"text": "hermes CLI not found in PATH"},
            )
            return False
        except Exception as exc:  # noqa: BLE001
            store.update_agent(agent_id, acp_status="crashed")
            store.push_event(
                "agent.acp.failed",
                agent_id,
                None,
                {"text": f"failed to start ACP: {exc}"},
            )
            return False
        with self._lock:
            self.clients[agent_id] = client
        store.update_agent(agent_id, acp_status="running", status="idle", current_task="空闲")
        store.push_event(
            "agent.acp.started",
            agent_id,
            None,
            {"text": f"ACP 进程已启动（profile={profile_name}）"},
        )
        return True

    def stop(self, agent_id: str) -> None:
        with self._lock:
            client = self.clients.pop(agent_id, None)
            self.pending_reply_to.pop(agent_id, None)
        if client is not None:
            client.close()
        store.update_agent(agent_id, acp_status="stopped", status="offline", current_task="已停止")
        store.push_event(
            "agent.acp.stopped",
            agent_id,
            None,
            {"text": "ACP 进程已停止"},
        )

    def prompt(
        self,
        agent_id: str,
        content: str,
        *,
        reply_to_leader: str | None = None,
    ) -> None:
        with self._lock:
            client = self.clients.get(agent_id)
            if client is None:
                raise RuntimeError("agent is not running; start it first")
            if reply_to_leader:
                self.pending_reply_to[agent_id] = reply_to_leader
        store.update_agent(agent_id, status="busy", current_task="处理消息中")
        try:
            client.prompt(content)
        except Exception:
            store.update_agent(agent_id, status="idle", current_task="空闲")
            with self._lock:
                self.pending_reply_to.pop(agent_id, None)
            raise

    def _on_final(self, agent_id: str, reply: str) -> None:
        with self._lock:
            leader_id = self.pending_reply_to.pop(agent_id, None)
        preview = (reply[:180] + "…") if len(reply) > 180 else (reply or "—")
        store.update_agent(
            agent_id,
            status="idle",
            current_task="空闲",
            last_output=preview,
        )
        store.push_event(
            "agent.output.final",
            agent_id,
            None,
            {"text": reply or "(空响应)"},
        )
        if leader_id:
            with self._lock:
                leader_client = self.clients.get(leader_id)
            if leader_client is not None:
                worker = store.find_agent(agent_id) or {}
                name = worker.get("name") or agent_id
                try:
                    self.prompt(
                        leader_id,
                        f"[来自 {name} 的回复]: {reply}",
                    )
                except Exception as exc:  # noqa: BLE001
                    store.push_event(
                        "agent.output.failed",
                        leader_id,
                        None,
                        {"text": f"回推 leader 失败：{exc}"},
                    )

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self.clients.keys())
        for aid in ids:
            self.stop(aid)


pool = ACPPool()
