"""HermesSession — per-agent pexpect wrapper around `hermes -p <profile>`.

Holds the interactive subprocess, its message queue, terminal buffer and
pending-interaction state machine. Detection / ANSI helpers live in
`helpers.py`; the ACPPool that manages HermesSession lifecycles lives in
`pool.py`.
"""
from __future__ import annotations

import os
import queue
import re
import threading
import time
from collections import deque
from itertools import count
from typing import Any
from uuid import uuid4

import pexpect
import pyte

from ...models.store import store
from .helpers import (
    APPROVAL_PATTERNS,
    INPUT_PATTERNS,
    MAX_RAW_OUTPUT_CHARS,
    MAX_TERMINAL_BUFFER_CHARS,
    MAX_TERMINAL_SUBSCRIBER_QUEUE,
    READ_CHUNK_SIZE,
    READ_LOOP_INTERVAL,
    RESOLVED_INTERACTION_SUPPRESS_SECONDS,
    TERMINAL_COLUMNS,
    TERMINAL_LINES,
    TERMINAL_QUEUE_CLOSE_SENTINEL,
    _clean_agent_reply,
    _compact_screen_text,
    _extract_selection,
    _has_active_selection_prompt,
    _has_interrupt_hint,
    _interaction_signature,
    _is_substantive_output,
    _is_suspicious_terminal_text,
    _log_state,
    _log_terminal_debug,
    _looks_ready_for_next_input,
    _screen_to_ansi,
    _should_show_stuck_hint,
    _strip_ansi,
    _terminal_preview,
)


class HermesSession:
    def __init__(
        self, profile_name: str, agent_id: str, workspace_path: str, on_final
    ) -> None:
        self.profile_name = profile_name
        self.agent_id = agent_id
        self.workspace_path = workspace_path
        self.on_final = on_final
        self._lock = threading.Lock()
        self._queue: deque[dict[str, Any]] = deque()
        self._counter = count(1)
        self._raw_output = ""
        self._terminal_screen = pyte.Screen(TERMINAL_COLUMNS, TERMINAL_LINES)
        self._terminal_stream = pyte.Stream(self._terminal_screen)
        self._last_terminal_snapshot = ""
        self._current_output: list[str] = []
        self._current_message: dict[str, Any] | None = None
        self._current_had_interrupt_hint = False
        self._current_saw_substantive_output = False
        self._current_stuck_hint_sent = False
        self._manual_terminal_active = False
        self._manual_terminal_user_task_id: str | None = None
        self._manual_terminal_buffer = ""
        self._manual_terminal_output: list[str] = []
        self._manual_terminal_started_at = 0.0
        self._manual_terminal_had_interrupt_hint = False
        self._manual_terminal_saw_substantive_output = False
        self._manual_terminal_stuck_hint_sent = False
        self._pending_interaction: dict[str, Any] | None = None
        self._terminal_interaction_buffer = ""
        self._terminal_selection_index: int | None = None
        self._recently_resolved_interactions: dict[str, float] = {}
        self._closed = False
        self._last_output_at = time.monotonic()
        self._current_started_at = 0.0
        self._terminal_rows = TERMINAL_LINES
        self._terminal_columns = TERMINAL_COLUMNS
        self._terminal_subscribers: set[queue.Queue[dict[str, Any]]] = set()
        self._terminal_buffer: deque[str] = deque()
        self._terminal_buffer_chars = 0
        self._terminal_debug_chunk_samples = 0
        self._last_terminal_warning_at = 0.0

        self.proc = pexpect.spawn(
            "hermes",
            ["-p", profile_name],
            cwd=workspace_path,
            encoding="utf-8",
            echo=False,
            timeout=None,
            dimensions=(TERMINAL_LINES, TERMINAL_COLUMNS),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        threading.Thread(target=self._reader_loop, daemon=True).start()

    # ------------------------------------------------------------------ state
    def _tail(self, limit: int = 800) -> str:
        with self._lock:
            return self._raw_output[-limit:]

    def _remember_terminal_chunk_locked(self, chunk: str) -> None:
        if not chunk:
            return
        self._terminal_buffer.append(chunk)
        self._terminal_buffer_chars += len(chunk)
        while self._terminal_buffer and self._terminal_buffer_chars > MAX_TERMINAL_BUFFER_CHARS:
            removed = self._terminal_buffer.popleft()
            self._terminal_buffer_chars -= len(removed)

    def _broadcast_terminal_message(self, message: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._terminal_subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(message)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(message)
                except (queue.Empty, queue.Full):  # noqa: PERF203
                    continue
            except Exception:  # noqa: BLE001
                continue

    def _write_terminal_notice(self, text: str) -> None:
        chunk = f"\r\n\x1b[33m[Hermes]\x1b[0m {text}\r\n"
        with self._lock:
            self._remember_terminal_chunk_locked(chunk)
            self._terminal_stream.feed(chunk)
            self._last_terminal_snapshot = _compact_screen_text(self._terminal_screen)
        self._broadcast_terminal_message({"type": "output", "data": chunk})
        store.push_event(
            "agent.terminal.output",
            self.agent_id,
            None,
            {"text": chunk},
        )

    def _message_notice_text(self, item: dict[str, Any]) -> str:
        preview = _strip_ansi(item.get("text") or "").replace("\r", " ").replace("\n", " ")
        preview = " ".join(preview.split())
        if len(preview) > 160:
            preview = f"{preview[:160]}…"
        if item.get("assignment_id"):
            return f"收到派发任务 {item['assignment_id']}：{preview}"
        return f"收到消息：{preview}"

    def open_terminal_stream(self) -> tuple[queue.Queue[dict[str, Any]], dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(
            maxsize=MAX_TERMINAL_SUBSCRIBER_QUEUE
        )
        with self._lock:
            if self._closed or not self.proc.isalive():
                raise RuntimeError("agent session is not running; start it first")
            self._terminal_subscribers.add(subscriber)
            raw_snapshot = "".join(self._terminal_buffer)
            state = {
                "rows": self._terminal_rows,
                "cols": self._terminal_columns,
                "snapshot_text": self._last_terminal_snapshot,
                "snapshot_ansi": raw_snapshot or _screen_to_ansi(self._terminal_screen),
            }
        return subscriber, state

    def close_terminal_stream(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._terminal_subscribers.discard(subscriber)
        try:
            subscriber.put_nowait(TERMINAL_QUEUE_CLOSE_SENTINEL)
        except queue.Full:
            try:
                subscriber.get_nowait()
                subscriber.put_nowait(TERMINAL_QUEUE_CLOSE_SENTINEL)
            except (queue.Empty, queue.Full):  # noqa: PERF203
                pass

    def _update_queue_depth(self) -> None:
        with self._lock:
            queue_depth = len(self._queue)
            if self._current_message is not None:
                queue_depth += 1
        store.update_agent(self.agent_id, queue_depth=queue_depth)
        _log_state("queue_depth", self.agent_id, depth=queue_depth)
        store.push_event(
            "agent.queue.updated",
            self.agent_id,
            None,
            {"text": f"queue_depth={queue_depth}"},
        )

    def _set_interaction(
        self,
        kind: str,
        prompt: str,
        *,
        choices: list[str] | None = None,
        selected_index: int | None = None,
    ) -> None:
        request_id = f"req_{uuid4().hex[:10]}"
        signature = _interaction_signature(kind, choices, prompt)
        now = time.monotonic()
        pending = {
            "request_id": request_id,
            "kind": kind,
            "prompt": prompt.strip()[-600:],
            "choices": choices if choices is not None else (["y", "n"] if kind == "awaiting_approval" else []),
            "selected_index": selected_index,
            "signature": signature,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with self._lock:
            self._recently_resolved_interactions = {
                key: resolved_at
                for key, resolved_at in self._recently_resolved_interactions.items()
                if now - resolved_at < RESOLVED_INTERACTION_SUPPRESS_SECONDS
            }
            if signature in self._recently_resolved_interactions:
                return
            if self._pending_interaction is not None:
                return
            self._pending_interaction = pending
            self._terminal_interaction_buffer = ""
            self._terminal_selection_index = selected_index
        store.update_agent(
            self.agent_id,
            status="waiting",
            current_task=(
                "等待人工确认"
                if kind == "awaiting_approval"
                else ("等待人工选择" if kind == "awaiting_selection" else "等待人工输入")
            ),
            interaction_state=kind,
            pending_interaction=pending,
        )
        _log_state("interaction_required", self.agent_id, kind=kind, request_id=request_id)
        store.push_event(
            "agent.interaction.required",
            self.agent_id,
            None,
            {"text": pending["prompt"], "interaction": pending},
        )

    def _clear_interaction(self, response: str) -> None:
        with self._lock:
            pending = self._pending_interaction
            self._pending_interaction = None
        if pending is None:
            return
        with self._lock:
            self._terminal_interaction_buffer = ""
            self._terminal_selection_index = None
        signature = pending.get("signature")
        if signature:
            with self._lock:
                self._recently_resolved_interactions[signature] = time.monotonic()
        store.update_agent(
            self.agent_id,
            status="busy",
            current_task="处理消息中",
            interaction_state="running",
            pending_interaction=None,
        )
        _log_state("interaction_resolved", self.agent_id, kind=pending.get("kind"), response=response)
        store.push_event(
            "agent.interaction.resolved",
            self.agent_id,
            None,
            {"text": f"{pending['kind']} -> {response}", "interaction": pending},
        )

    def _clear_stale_selection_if_needed(self, terminal_snapshot: str, *, active: bool) -> bool:
        with self._lock:
            pending = self._pending_interaction
            if not pending or pending.get("kind") != "awaiting_selection":
                return False
            if _has_active_selection_prompt(terminal_snapshot):
                return False
            if not _looks_ready_for_next_input(terminal_snapshot):
                return False
            self._pending_interaction = None
            self._terminal_interaction_buffer = ""
            self._terminal_selection_index = None
            signature = pending.get("signature")
            if signature:
                self._recently_resolved_interactions[signature] = time.monotonic()
        store.update_agent(
            self.agent_id,
            status="busy" if active else "idle",
            current_task="处理消息中" if active else "空闲",
            interaction_state="running" if active else "idle",
            pending_interaction=None,
        )
        _log_state("stale_selection_cleared", self.agent_id, request_id=pending.get("request_id"))
        return True

    def _detect_interaction(self, text: str, *, selection_text: str | None = None) -> bool:
        selection_source = selection_text if selection_text is not None else text
        selection = _extract_selection(selection_source)
        if selection is not None:
            self._set_interaction(
                "awaiting_selection",
                selection_source,
                choices=selection["choices"],
                selected_index=selection["selected_index"],
            )
            return True
        if any(pattern.search(text) for pattern in APPROVAL_PATTERNS):
            self._set_interaction("awaiting_approval", text)
            return True
        if any(pattern.search(text) for pattern in INPUT_PATTERNS):
            self._set_interaction("awaiting_input", text)
            return True
        return False

    def _mark_crashed(self, reason: str) -> None:
        failed_message = None
        with self._lock:
            self._pending_interaction = None
            if self._current_message is not None:
                failed_message = self._current_message
                if not (
                    failed_message.get("reply_to_leader")
                    and failed_message.get("delegation_id")
                    and failed_message.get("assignment_id")
                ):
                    self._queue.appendleft(failed_message)
            self._current_message = None
        store.update_agent(
            self.agent_id,
            runtime_status="crashed",
            interaction_state="failed",
            pending_interaction=None,
            status="offline",
            current_task="会话异常退出",
        )
        _log_state("crashed", self.agent_id, reason=reason, failed_message=bool(failed_message))
        self._update_queue_depth()
        store.push_event(
            "agent.runtime.failed",
            self.agent_id,
            None,
            {"text": f"Hermes session ended: {reason}"},
        )
        self._broadcast_terminal_message(
            {
                "type": "status",
                "status": "error",
                "message": f"Hermes session ended: {reason}",
            }
        )
        if (
            failed_message
            and failed_message.get("reply_to_leader")
            and failed_message.get("delegation_id")
            and failed_message.get("assignment_id")
        ):
            try:
                self.on_final(
                    self.agent_id,
                    f"会话异常退出：{reason}",
                    failed_message.get("reply_to_leader"),
                    failed_message.get("delegation_id"),
                    failed_message.get("assignment_id"),
                    failed_message.get("user_task_id"),
                    failed_message.get("summarize_delegation_id"),
                    failed_message.get("summarize_user_task_id"),
                    True,
                )
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "agent.output.failed",
                    self.agent_id,
                    failed_message.get("delegation_id"),
                    {"text": f"failure handler error: {exc}"},
                )

    # ------------------------------------------------------------------ io
    def _send_line(self, text: str) -> None:
        if self._closed:
            return
        # Hermes runs a full-screen TUI. Multi-line prompts sent with a plain
        # sendline can be interpreted as multiple Enter presses inside the UI.
        # Bracketed paste preserves the prompt as a single input, then Enter
        # submits it.
        self.proc.send("\x1b[200~")
        self.proc.send(text)
        self.proc.send("\x1b[201~")
        self.proc.send("\r")

    def _send_selection(self, target_index: int, selected_index: int) -> None:
        if self._closed:
            return
        delta = target_index - selected_index
        if delta > 0:
            self.proc.send("\x1b[B" * delta)
        elif delta < 0:
            self.proc.send("\x1b[A" * abs(delta))
        self.proc.send("\r")

    def _send_terminal_data(self, data: str) -> None:
        if self._closed or not data:
            return
        self.proc.send(data)

    def _track_terminal_interaction_data(self, data: str) -> None:
        submitted = "\r" in data or "\n" in data
        with self._lock:
            pending = self._pending_interaction
            if pending is None:
                buffer = self._manual_terminal_buffer
                cursor = 0
                while cursor < len(data):
                    if data.startswith("\x1b[200~", cursor):
                        cursor += 6
                        continue
                    if data.startswith("\x1b[201~", cursor):
                        cursor += 6
                        continue
                    if data[cursor] == "\x1b":
                        match = re.match(r"\x1b\[[0-9;?]*[A-Za-z~]|\x1bO[A-Za-z]", data[cursor:])
                        cursor += len(match.group(0)) if match else 1
                        continue
                    char = data[cursor]
                    if char in "\r\n":
                        cursor += 1
                        continue
                    if char in ("\b", "\x7f"):
                        buffer = buffer[:-1]
                    elif char >= " ":
                        buffer += char
                    cursor += 1
                if submitted and buffer.strip():
                    self._manual_terminal_active = True
                    self._manual_terminal_output = []
                    self._manual_terminal_started_at = time.monotonic()
                    self._manual_terminal_had_interrupt_hint = False
                    self._manual_terminal_saw_substantive_output = False
                    self._manual_terminal_stuck_hint_sent = False
                    self._last_output_at = self._manual_terminal_started_at
                    self._manual_terminal_buffer = ""
                    submitted_text = buffer.strip()
                else:
                    self._manual_terminal_buffer = buffer if not submitted else ""
                    submitted_text = ""
                if not submitted_text:
                    return
                pending = None
            else:
                submitted_text = ""
        if pending is None:
            user_task_id = None
            agent = store.find_agent(self.agent_id) or {}
            if agent.get("role") == "leader":
                try:
                    user_task = store.create_user_task(
                        leader_agent_id=self.agent_id,
                        content=submitted_text,
                    )
                    user_task_id = user_task["user_task_id"]
                except Exception as exc:  # noqa: BLE001
                    store.push_event(
                        "user_task.create.failed",
                        self.agent_id,
                        None,
                        {"text": f"终端任务创建失败：{exc}"},
                    )
            with self._lock:
                if self._manual_terminal_active:
                    self._manual_terminal_user_task_id = user_task_id
            store.update_agent(
                self.agent_id,
                status="busy",
                current_task="终端处理中",
                interaction_state="running",
            )
            _log_state(
                "terminal_manual_start",
                self.agent_id,
                chars=len(submitted_text),
                user_task_id=user_task_id,
            )
            return
        with self._lock:
            choices = list(pending.get("choices") or [])
            if pending.get("kind") == "awaiting_selection" and choices:
                current_index = self._terminal_selection_index
                if current_index is None:
                    current_index = int(pending.get("selected_index") or 0)
                current_index = max(0, min(current_index, len(choices) - 1))
                cursor = 0
                while cursor < len(data):
                    if data.startswith("\x1b[A", cursor) or data.startswith("\x1bOA", cursor):
                        current_index = max(0, current_index - 1)
                        cursor += 3
                        continue
                    if data.startswith("\x1b[B", cursor) or data.startswith("\x1bOB", cursor):
                        current_index = min(len(choices) - 1, current_index + 1)
                        cursor += 3
                        continue
                    cursor += 1
                self._terminal_selection_index = current_index
                response = choices[current_index] if submitted else ""
            else:
                buffer = self._terminal_interaction_buffer
                cursor = 0
                while cursor < len(data):
                    if data.startswith("\x1b[200~", cursor):
                        cursor += 6
                        continue
                    if data.startswith("\x1b[201~", cursor):
                        cursor += 6
                        continue
                    if data[cursor] == "\x1b":
                        match = re.match(r"\x1b\[[0-9;?]*[A-Za-z~]|\x1bO[A-Za-z]", data[cursor:])
                        cursor += len(match.group(0)) if match else 1
                        continue
                    char = data[cursor]
                    if char in "\r\n":
                        cursor += 1
                        continue
                    if char in ("\b", "\x7f"):
                        buffer = buffer[:-1]
                    elif char >= " ":
                        buffer += char
                    cursor += 1
                self._terminal_interaction_buffer = buffer
                response = buffer.strip() if submitted else ""
        if submitted:
            self._clear_interaction(response or "terminal submit")
            self._last_output_at = time.monotonic()

    def _finalize_manual_terminal(self) -> None:
        with self._lock:
            if not self._manual_terminal_active:
                return
            reply = _clean_agent_reply("".join(self._manual_terminal_output))
            user_task_id = self._manual_terminal_user_task_id
            self._manual_terminal_active = False
            self._manual_terminal_user_task_id = None
            self._manual_terminal_output = []
            self._manual_terminal_started_at = 0.0
            self._manual_terminal_had_interrupt_hint = False
            self._manual_terminal_saw_substantive_output = False
            self._manual_terminal_stuck_hint_sent = False
            queued = bool(self._queue or self._current_message)
        store.update_agent(
            self.agent_id,
            status="busy" if queued else "idle",
            current_task="等待队列执行" if queued else "空闲",
            interaction_state="queued" if queued else "idle",
            last_output=(reply[:180] + "…") if len(reply) > 180 else (reply or "—"),
            last_output_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        _log_state("terminal_manual_final", self.agent_id, reply_len=len(reply), queued=queued)
        if user_task_id:
            try:
                self.on_final(
                    self.agent_id,
                    reply,
                    None,
                    None,
                    None,
                    user_task_id,
                    None,
                    None,
                    False,
                )
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "user_task.dispatch.failed",
                    self.agent_id,
                    user_task_id,
                    {"text": f"关闭终端用户任务失败：{exc}"},
                )
        self._dispatch_next()

    def _resize_terminal(self, rows: int, columns: int) -> None:
        rows = max(10, min(int(rows), 120))
        columns = max(40, min(int(columns), 240))
        if self._closed:
            return
        try:
            self.proc.setwinsize(rows, columns)
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            self._terminal_rows = rows
            self._terminal_columns = columns
            try:
                self._terminal_screen.resize(rows, columns)
            except Exception:  # noqa: BLE001
                self._terminal_screen = pyte.Screen(columns, rows)
                self._terminal_stream = pyte.Stream(self._terminal_screen)

    def _dispatch_next(self) -> None:
        with self._lock:
            if self._closed or self._pending_interaction is not None or self._current_message is not None:
                _log_state(
                    "dispatch_skip",
                    self.agent_id,
                    closed=self._closed,
                    pending=bool(self._pending_interaction),
                    current=bool(self._current_message),
                    queue=len(self._queue),
                )
                return
            if not self._queue:
                if self._manual_terminal_active:
                    store.update_agent(
                        self.agent_id,
                        status="busy",
                        current_task="终端处理中",
                        interaction_state="running",
                    )
                    _log_state("dispatch_idle_manual_active", self.agent_id)
                    return
                agent = store.find_agent(self.agent_id) or {}
                orchestration_state = agent.get("orchestration_state")
                active_tasks = (
                    store.count_active_user_tasks(self.agent_id)
                    if agent.get("role") == "leader"
                    else 0
                )
                if active_tasks:
                    current_task = (
                        "汇总 worker 结果中"
                        if orchestration_state == "summarizing"
                        else "等待 worker 返回"
                    )
                    store.update_agent(
                        self.agent_id,
                        status="busy",
                        current_task=current_task,
                        interaction_state="queued",
                    )
                    _log_state("dispatch_idle_active_task", self.agent_id, active_tasks=active_tasks, orchestration_state=orchestration_state)
                else:
                    current_task = (
                        "等待 worker 返回"
                        if orchestration_state == "waiting_workers"
                        else "空闲"
                    )
                    store.update_agent(
                        self.agent_id,
                        status="idle",
                        current_task=current_task,
                        interaction_state="idle",
                    )
                    _log_state("dispatch_idle", self.agent_id, orchestration_state=orchestration_state)
                try:
                    from ..kanban_sync import sync_worker
                    sync_worker.sync_agent(self.agent_id)
                except Exception:  # noqa: BLE001
                    pass
                return
            message = self._queue.popleft()
            self._current_message = message
            self._current_output = []
            self._current_had_interrupt_hint = False
            self._current_saw_substantive_output = False
            self._current_stuck_hint_sent = False
            self._current_started_at = time.monotonic()
            self._last_output_at = self._current_started_at
        store.update_agent(
            self.agent_id,
            status="busy",
            current_task="处理消息中",
            interaction_state="running",
        )
        _log_state(
            "dispatch_start",
            self.agent_id,
            job_id=message.get("id"),
            delegation_id=message.get("delegation_id"),
            assignment_id=message.get("assignment_id"),
            user_task_id=message.get("user_task_id"),
            queue=len(self._queue),
        )
        self._update_queue_depth()
        try:
            self._send_line(message["text"])
        except Exception as exc:  # noqa: BLE001
            self._mark_crashed(f"stdin write failed: {exc}")

    def _finalize_current(self) -> None:
        with self._lock:
            message = self._current_message
            if message is None:
                return
            reply = _clean_agent_reply("".join(self._current_output))
            self._current_message = None
            self._current_output = []
            self._current_had_interrupt_hint = False
            self._current_saw_substantive_output = False

        preview = (reply[:180] + "…") if len(reply) > 180 else (reply or "—")
        agent = store.find_agent(self.agent_id) or {}
        active_tasks = (
            store.count_active_user_tasks(
                self.agent_id,
                exclude_user_task_id=message.get("user_task_id"),
            )
            if agent.get("role") == "leader"
            else 0
        )
        next_state = "queued" if self._queue or active_tasks else "idle"
        next_status = "busy" if self._queue or active_tasks else "idle"
        orchestration_state = agent.get("orchestration_state")
        next_task = "等待队列执行" if self._queue else ("等待 worker 返回" if active_tasks else "空闲")
        if not self._queue and orchestration_state == "waiting_workers":
            next_task = "等待 worker 返回"
        store.update_agent(
            self.agent_id,
            status=next_status,
            current_task=next_task,
            interaction_state=next_state,
            last_output=preview,
            last_output_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        _log_state(
            "finalize",
            self.agent_id,
            job_id=message.get("id"),
            next_status=next_status,
            next_state=next_state,
            reply_len=len(reply),
            queue=len(self._queue),
            active_tasks=active_tasks,
            delegation_id=message.get("delegation_id"),
            assignment_id=message.get("assignment_id"),
            user_task_id=message.get("user_task_id"),
        )
        store.push_event(
            "agent.output.final",
            self.agent_id,
            None,
            {"text": reply or "(空响应)"},
        )
        self._update_queue_depth()
        try:
            self.on_final(
                self.agent_id,
                reply,
                message.get("reply_to_leader"),
                message.get("delegation_id"),
                message.get("assignment_id"),
                message.get("user_task_id"),
                message.get("summarize_delegation_id"),
                message.get("summarize_user_task_id"),
                False,
            )
        except Exception as exc:  # noqa: BLE001
            store.push_event(
                "agent.output.failed",
                self.agent_id,
                None,
                {"text": f"final handler error: {exc}"},
            )
        self._dispatch_next()

    def _handle_chunk(self, chunk: str) -> None:
        terminal_chunk = chunk.replace("\r\n", "\n")
        clean = _strip_ansi(chunk.replace("\r", ""))
        now = time.monotonic()
        with self._lock:
            should_log_sample = self._terminal_debug_chunk_samples < 5
            suspicious_chunk = _is_suspicious_terminal_text(terminal_chunk)
            should_log_warning = suspicious_chunk and (now - self._last_terminal_warning_at >= 1.5)
            if should_log_sample:
                self._terminal_debug_chunk_samples += 1
            if should_log_warning:
                self._last_terminal_warning_at = now
            self._remember_terminal_chunk_locked(terminal_chunk)
            running = self._current_message is not None
            self._terminal_stream.feed(terminal_chunk)
            terminal_snapshot = _compact_screen_text(self._terminal_screen)
            snapshot_changed = terminal_snapshot != self._last_terminal_snapshot
            if snapshot_changed:
                self._last_terminal_snapshot = terminal_snapshot
            self._raw_output = (self._raw_output + clean)[-MAX_RAW_OUTPUT_CHARS:]
            if running:
                self._current_output.append(clean)
                if _has_interrupt_hint(clean) or _has_interrupt_hint(terminal_snapshot):
                    self._current_had_interrupt_hint = True
                if _is_substantive_output(clean):
                    self._current_saw_substantive_output = True
                    self._current_stuck_hint_sent = False
                    self._last_output_at = now
            manual_active = self._manual_terminal_active and not running
            if manual_active:
                self._manual_terminal_output.append(clean)
                if _has_interrupt_hint(clean) or _has_interrupt_hint(terminal_snapshot):
                    self._manual_terminal_had_interrupt_hint = True
                if _is_substantive_output(clean):
                    self._manual_terminal_saw_substantive_output = True
                    self._manual_terminal_stuck_hint_sent = False
                    self._last_output_at = now
            pending = self._pending_interaction
            current_text = "".join(self._current_output)[-2000:]
            current_had_interrupt_hint = self._current_had_interrupt_hint
            current_saw_substantive_output = self._current_saw_substantive_output
            manual_text = "".join(self._manual_terminal_output)[-2000:]
            manual_had_interrupt_hint = self._manual_terminal_had_interrupt_hint
            manual_saw_substantive_output = self._manual_terminal_saw_substantive_output

        if should_log_sample:
            _log_terminal_debug(
                "chunk_sample",
                self.agent_id,
                terminal_chunk,
                clean_preview=_terminal_preview(clean),
                running=running,
            )
        if should_log_warning:
            _log_terminal_debug(
                "chunk_suspicious",
                self.agent_id,
                terminal_chunk,
                clean_preview=_terminal_preview(clean),
                running=running,
            )

        self._broadcast_terminal_message(
            {"type": "output", "data": terminal_chunk}
        )

        store.push_event(
            "agent.terminal.output",
            self.agent_id,
            None,
            {"text": terminal_chunk},
        )

        if snapshot_changed:
            if _is_suspicious_terminal_text(terminal_snapshot):
                _log_terminal_debug("snapshot_suspicious", self.agent_id, terminal_snapshot)
            store.push_event(
                "agent.terminal.snapshot",
                self.agent_id,
                None,
                {"text": terminal_snapshot},
            )

        if running:
            agent = store.find_agent(self.agent_id) or {}
            if (
                agent.get("status") != "busy"
                or agent.get("interaction_state") != "running"
                or agent.get("current_task") == "处理中，可能卡住"
            ):
                store.update_agent(
                    self.agent_id,
                    status="busy",
                    current_task="处理消息中",
                    interaction_state="running",
                )
                _log_state("running_from_chunk", self.agent_id, chunk_len=len(chunk))
        elif manual_active:
            agent = store.find_agent(self.agent_id) or {}
            if agent.get("current_task") == "终端处理中，可能卡住":
                store.update_agent(
                    self.agent_id,
                    status="busy",
                    current_task="终端处理中",
                    interaction_state="running",
                )
                _log_state("terminal_manual_resumed_from_chunk", self.agent_id, chunk_len=len(chunk))

        if pending is not None and not self._clear_stale_selection_if_needed(terminal_snapshot, active=running or manual_active):
            return

        recent = self._tail(2000)
        detection_text = f"{terminal_snapshot}\n{recent}"
        if not running:
            if self._detect_interaction(detection_text, selection_text=terminal_snapshot):
                return
            if (
                manual_active
                and manual_saw_substantive_output
                and _looks_ready_for_next_input(manual_text, terminal_snapshot)
                and not _has_interrupt_hint(manual_text)
                and not _has_interrupt_hint(terminal_snapshot)
            ):
                _log_state(
                    "terminal_manual_ready_detected",
                    self.agent_id,
                    current_tail=manual_text[-160:],
                    had_interrupt_hint=manual_had_interrupt_hint,
                )
                self._finalize_manual_terminal()
            return
        if self._detect_interaction(detection_text, selection_text=terminal_snapshot):
            return
        if (
            current_saw_substantive_output
            and _looks_ready_for_next_input(current_text, terminal_snapshot)
            and not _has_interrupt_hint(current_text)
            and not _has_interrupt_hint(terminal_snapshot)
        ):
            _log_state(
                "ready_detected",
                self.agent_id,
                current_tail=current_text[-160:],
                had_interrupt_hint=current_had_interrupt_hint,
            )
            self._finalize_current()

    def _reader_loop(self) -> None:
        while not self._closed:
            if not self.proc.isalive():
                self._mark_crashed("process exited")
                return
            try:
                chunk = self.proc.read_nonblocking(size=READ_CHUNK_SIZE, timeout=READ_LOOP_INTERVAL)
            except pexpect.TIMEOUT:
                chunk = ""
            except pexpect.EOF:
                self._mark_crashed("EOF")
                return
            except Exception as exc:  # noqa: BLE001
                self._mark_crashed(str(exc))
                return

            if chunk:
                self._handle_chunk(chunk)
                continue

            with self._lock:
                now = time.monotonic()
                interaction_text = f"{self._last_terminal_snapshot}\n{self._raw_output[-2000:]}"
                current_text = "".join(self._current_output)[-2000:]
                should_finalize_ready = (
                    self._current_message is not None
                    and self._current_saw_substantive_output
                    and _looks_ready_for_next_input(current_text, self._last_terminal_snapshot)
                    and not _has_interrupt_hint(current_text)
                    and not _has_interrupt_hint(self._last_terminal_snapshot)
                )
                should_hint_stuck = _should_show_stuck_hint(
                    active=self._current_message is not None,
                    pending_interaction=self._pending_interaction is not None,
                    started_at=self._current_started_at,
                    last_output_at=self._last_output_at,
                    hint_sent=self._current_stuck_hint_sent,
                    now=now,
                )
                should_hint_manual_stuck = _should_show_stuck_hint(
                    active=self._manual_terminal_active and self._current_message is None,
                    pending_interaction=self._pending_interaction is not None,
                    started_at=self._manual_terminal_started_at,
                    last_output_at=self._last_output_at,
                    hint_sent=self._manual_terminal_stuck_hint_sent,
                    now=now,
                )
            if should_finalize_ready:
                _log_state("ready_detected_idle", self.agent_id)
                self._finalize_current()
                continue
            if should_hint_stuck:
                if self._detect_interaction(interaction_text, selection_text=self._last_terminal_snapshot):
                    continue
                with self._lock:
                    self._current_stuck_hint_sent = True
                _log_state(
                    "stuck_hint",
                    self.agent_id,
                    idle_for=round(time.monotonic() - self._last_output_at, 2),
                )
                store.update_agent(
                    self.agent_id,
                    status="busy",
                    current_task="处理中，可能卡住",
                    interaction_state="running",
                )
            if should_hint_manual_stuck:
                if self._detect_interaction(interaction_text, selection_text=self._last_terminal_snapshot):
                    continue
                with self._lock:
                    self._manual_terminal_stuck_hint_sent = True
                _log_state(
                    "terminal_manual_stuck_hint",
                    self.agent_id,
                    idle_for=round(time.monotonic() - self._last_output_at, 2),
                )
                store.update_agent(
                    self.agent_id,
                    status="busy",
                    current_task="终端处理中，可能卡住",
                    interaction_state="running",
                )

    # ------------------------------------------------------------------ api
    def enqueue_message(
        self,
        text: str,
        *,
        reply_to_leader: str | None = None,
        delegation_id: str | None = None,
        assignment_id: str | None = None,
        user_task_id: str | None = None,
        summarize_delegation_id: str | None = None,
        summarize_user_task_id: str | None = None,
    ) -> None:
        item = {
            "id": f"job_{next(self._counter):04d}",
            "text": text,
            "reply_to_leader": reply_to_leader,
            "delegation_id": delegation_id,
            "assignment_id": assignment_id,
            "user_task_id": user_task_id,
            "summarize_delegation_id": summarize_delegation_id,
            "summarize_user_task_id": summarize_user_task_id,
        }
        with self._lock:
            self._queue.append(item)
            current_busy = self._current_message is not None or self._pending_interaction is not None
            queue_depth = len(self._queue)
        _log_state(
            "enqueue",
            self.agent_id,
            job_id=item["id"],
            current_busy=current_busy,
            queue=queue_depth,
            delegation_id=delegation_id,
            assignment_id=assignment_id,
            user_task_id=user_task_id,
            summarize_user_task_id=summarize_user_task_id,
        )
        store.update_agent(
            self.agent_id,
            status="busy",
            current_task="等待队列执行" if current_busy else "准备处理消息",
            interaction_state="queued",
        )
        self._write_terminal_notice(self._message_notice_text(item))
        self._update_queue_depth()
        self._dispatch_next()

    def respond_interaction(self, request_id: str, response: str) -> None:
        response = (response or "").strip()
        if not response:
            raise ValueError("response is required")
        with self._lock:
            pending = self._pending_interaction
        if pending is None:
            raise ValueError("agent is not waiting for interaction")
        if pending["request_id"] != request_id:
            raise ValueError("interaction request_id mismatch")
        pending_selection = _extract_selection(pending.get("prompt") or "")
        if pending.get("kind") == "awaiting_selection" or pending_selection is not None:
            choices = (pending_selection or {}).get("choices") or pending.get("choices") or []
            selected_index = int((pending_selection or {}).get("selected_index") or pending.get("selected_index") or 0)
            signature = _interaction_signature("awaiting_selection", choices)
            with self._lock:
                self._recently_resolved_interactions[signature] = time.monotonic()
            try:
                target_index = int(response)
            except ValueError:
                target_index = choices.index(response) if response in choices else -1
            if target_index < 0 or target_index >= len(choices):
                raise ValueError("selection response is invalid")
            self._send_selection(target_index, selected_index)
            response = choices[target_index]
        else:
            self._send_line(response)
        self._clear_interaction(response)
        self._last_output_at = time.monotonic()

    def send_terminal_input(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            raise ValueError("text is required")
        self._send_line(text)
        store.push_event(
            "agent.terminal.input",
            self.agent_id,
            None,
            {"text": f"$ {text}"},
        )

    def send_terminal_data(self, data: str) -> None:
        if not data:
            raise ValueError("data is required")
        if "\r" in data or "\n" in data:
            _log_state("terminal_submit", self.agent_id, bytes=len(data))
        self._track_terminal_interaction_data(data)
        self._send_terminal_data(data)

    def resize_terminal(self, rows: int, columns: int) -> None:
        self._resize_terminal(rows, columns)

    def close(self) -> None:
        self._closed = True
        self._broadcast_terminal_message(
            {"type": "status", "status": "closed", "message": "Hermes session 已关闭"}
        )
        try:
            if self.proc.isalive():
                self.proc.close(force=True)
        except Exception:  # noqa: BLE001
            pass

    def take_pending_messages(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
        return items

    def restore_pending_messages(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        with self._lock:
            self._queue.extend(items)
        self._update_queue_depth()
        self._dispatch_next()

    def current_user_task_id(self) -> str | None:
        with self._lock:
            if self._current_message is not None:
                return self._current_message.get("user_task_id")
            if self._manual_terminal_active:
                return self._manual_terminal_user_task_id
            return None
