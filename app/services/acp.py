"""Per-agent persistent `hermes -p <profile>` session pool powered by pexpect.

Each HermesSession owns one interactive Hermes CLI process. Messages are queued
per agent to preserve session context. Output is streamed into the RuntimeStore,
and basic human-in-the-loop approvals/inputs are detected from terminal text.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from itertools import count
from typing import Any
from uuid import uuid4

import pexpect
import pyte

from ..models.store import store


SILENCE_TIMEOUT_SECONDS = 10.0
MAX_TURN_SECONDS = 120.0
READ_CHUNK_SIZE = 1024
READ_LOOP_INTERVAL = 0.2
MAX_RAW_OUTPUT_CHARS = 12000
TERMINAL_COLUMNS = 120
TERMINAL_LINES = 36
RESOLVED_INTERACTION_SUPPRESS_SECONDS = 30.0

READY_PATTERNS = (
    re.compile(r"(?m)^\s*(?:⚕\s*)?❯\s*$"),
)
INTERRUPT_HINT_PATTERN = re.compile(
    r"type a message \+ Enter to interrupt", re.IGNORECASE
)
APPROVAL_PATTERNS = (
    re.compile(r"\[(?:y/N|Y/n|yes/no)\]", re.IGNORECASE),
    re.compile(r"\b(?:approve|approval|allow)\b", re.IGNORECASE),
    re.compile(r"\bdo you want to run\b", re.IGNORECASE),
)
INPUT_PATTERNS = (
    re.compile(r"\b(?:enter|type|provide)\b.+\b(?:input|response|value)\b", re.IGNORECASE),
    re.compile(r"\bwaiting for input\b", re.IGNORECASE),
)
SELECTION_PATTERNS = (
    re.compile(r"\bto select,\s*Enter to confirm\b", re.IGNORECASE),
    re.compile(r"\bHermes needs your input\b", re.IGNORECASE),
)


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)


def _compact_screen_text(screen: pyte.Screen) -> str:
    return "\n".join(line.rstrip() for line in screen.display).rstrip()


def _is_substantive_output(text: str) -> bool:
    stripped = _strip_ansi(text).strip()
    if not stripped:
        return False
    if re.fullmatch(r"\d{1,4}s?", stripped):
        return False
    if "token usage" in stripped.lower():
        return False
    if "cursor position requests" in stripped.lower():
        return False
    if re.fullmatch(r"[\s\-─|$⚕❯\[\]░▒▓█.,:;_/\\]+", stripped):
        return False
    return True


def _has_interrupt_hint(text: str) -> bool:
    return bool(INTERRUPT_HINT_PATTERN.search(text))


def _clean_selection_line(line: str) -> str:
    return line.strip().strip("│┃║▏▕▌▐").rstrip("│┃║▏▕▌▐").strip()


def _clean_choice_label(label: str) -> str:
    label = re.sub(r"\s{2,}", " ", label).strip()
    label = re.sub(r"\s*\([0-9.]+s\)\s*$", "", label).strip()
    return label


def _extract_selection(text: str) -> dict[str, Any] | None:
    if not any(pattern.search(text) for pattern in SELECTION_PATTERNS):
        return None

    lines = [_clean_selection_line(line) for line in text.splitlines()]
    choice_pattern = re.compile(r"(?:\bagent_[\w-]+\b|Other \(type your answer\))", re.IGNORECASE)
    scanned_choices: list[str] = []
    scanned_selected_index: int | None = None
    for line in lines:
        if not line:
            continue
        selected_match = re.match(r"^[›>❯]\s*(.+?)\s*$", line)
        choice_line = selected_match.group(1) if selected_match else line
        if not selected_match and not choice_pattern.search(choice_line):
            continue
        label = _clean_choice_label(choice_line)
        if not label or label in scanned_choices:
            continue
        if selected_match:
            scanned_selected_index = len(scanned_choices)
        scanned_choices.append(label)

    if scanned_selected_index is not None and scanned_choices:
        return {"choices": scanned_choices, "selected_index": scanned_selected_index}

    selected_index: int | None = None
    choices: list[str] = []
    collecting = False

    for line in lines:
        if not line:
            if collecting and choices:
                break
            continue
        if re.search(r"\b(?:to select|Enter to confirm)\b", line, re.IGNORECASE):
            if collecting and choices:
                break
            continue

        selected_match = re.match(r"^[›>❯]\s*(.+?)\s*$", line)
        if selected_match:
            label = _clean_choice_label(selected_match.group(1))
            if label:
                selected_index = len(choices)
                choices.append(label)
                collecting = True
            continue

        if collecting:
            if line.startswith("?") or line.startswith("$"):
                break
            if re.match(r"^[┌└├╭╰─━═]+$", line):
                break
            if len(line) <= 140:
                choices.append(_clean_choice_label(line))

    if selected_index is None or not choices:
        return None
    return {"choices": choices, "selected_index": selected_index}


def _interaction_signature(kind: str, choices: list[str] | None = None, prompt: str = "") -> str:
    if choices:
        return f"{kind}:" + "|".join(_clean_choice_label(choice) for choice in choices)
    compact_prompt = re.sub(r"\s+", " ", _strip_ansi(prompt))[-240:]
    return f"{kind}:{compact_prompt}"


class HermesSession:
    def __init__(self, profile_name: str, agent_id: str, on_final) -> None:
        self.profile_name = profile_name
        self.agent_id = agent_id
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
        self._pending_interaction: dict[str, Any] | None = None
        self._terminal_interaction_buffer = ""
        self._terminal_selection_index: int | None = None
        self._recently_resolved_interactions: dict[str, float] = {}
        self._closed = False
        self._last_output_at = time.monotonic()
        self._current_started_at = 0.0

        self.proc = pexpect.spawn(
            "hermes",
            ["-p", profile_name],
            cwd=os.getcwd(),
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

    def _update_queue_depth(self) -> None:
        with self._lock:
            queue_depth = len(self._queue)
            if self._current_message is not None:
                queue_depth += 1
        store.update_agent(self.agent_id, queue_depth=queue_depth)
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
        store.push_event(
            "agent.interaction.resolved",
            self.agent_id,
            None,
            {"text": f"{pending['kind']} -> {response}", "interaction": pending},
        )

    def _detect_interaction(self, text: str) -> bool:
        selection = _extract_selection(text)
        if selection is not None:
            self._set_interaction(
                "awaiting_selection",
                text,
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
        with self._lock:
            self._pending_interaction = None
            if self._current_message is not None:
                self._queue.appendleft(self._current_message)
            self._current_message = None
        store.update_agent(
            self.agent_id,
            runtime_status="crashed",
            interaction_state="failed",
            pending_interaction=None,
            status="offline",
            current_task="会话异常退出",
        )
        self._update_queue_depth()
        store.push_event(
            "agent.runtime.failed",
            self.agent_id,
            None,
            {"text": f"Hermes session ended: {reason}"},
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
                return
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
            try:
                self._terminal_screen.resize(rows, columns)
            except Exception:  # noqa: BLE001
                self._terminal_screen = pyte.Screen(columns, rows)
                self._terminal_stream = pyte.Stream(self._terminal_screen)

    def _dispatch_next(self) -> None:
        with self._lock:
            if self._closed or self._pending_interaction is not None or self._current_message is not None:
                return
            if not self._queue:
                agent = store.find_agent(self.agent_id) or {}
                orchestration_state = agent.get("orchestration_state")
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
                return
            message = self._queue.popleft()
            self._current_message = message
            self._current_output = []
            self._current_started_at = time.monotonic()
            self._last_output_at = self._current_started_at
        store.update_agent(
            self.agent_id,
            status="busy",
            current_task="处理消息中",
            interaction_state="running",
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
            reply = _strip_ansi("".join(self._current_output)).strip()
            self._current_message = None
            self._current_output = []

        preview = (reply[:180] + "…") if len(reply) > 180 else (reply or "—")
        next_state = "queued" if self._queue else "idle"
        next_status = "busy" if self._queue else "idle"
        agent = store.find_agent(self.agent_id) or {}
        orchestration_state = agent.get("orchestration_state")
        next_task = "等待队列执行" if self._queue else "空闲"
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
                message.get("summarize_delegation_id"),
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
            running = self._current_message is not None
            self._terminal_stream.feed(terminal_chunk)
            terminal_snapshot = _compact_screen_text(self._terminal_screen)
            snapshot_changed = terminal_snapshot != self._last_terminal_snapshot
            if snapshot_changed:
                self._last_terminal_snapshot = terminal_snapshot
            self._raw_output = (self._raw_output + clean)[-MAX_RAW_OUTPUT_CHARS:]
            if running:
                self._current_output.append(clean)
                if _is_substantive_output(clean):
                    self._last_output_at = now
            pending = self._pending_interaction

        store.push_event(
            "agent.terminal.output",
            self.agent_id,
            None,
            {"text": terminal_chunk},
        )

        if snapshot_changed:
            store.push_event(
                "agent.terminal.snapshot",
                self.agent_id,
                None,
                {"text": terminal_snapshot},
            )

        if running:
            agent = store.find_agent(self.agent_id) or {}
            if agent.get("status") != "busy" or agent.get("interaction_state") != "running":
                store.update_agent(
                    self.agent_id,
                    status="busy",
                    current_task="处理消息中",
                    interaction_state="running",
                )

        if pending is not None:
            return

        recent = self._tail(2000)
        detection_text = f"{terminal_snapshot}\n{recent}"
        if not running:
            self._detect_interaction(detection_text)
            return
        if self._detect_interaction(detection_text):
            return
        if (
            any(pattern.search(detection_text) for pattern in READY_PATTERNS)
            and not _has_interrupt_hint(recent)
            and "".join(self._current_output).strip()
        ):
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
                interaction_text = f"{self._last_terminal_snapshot}\n{self._raw_output[-2000:]}"
                timed_out = (
                    self._current_message is not None
                    and self._pending_interaction is None
                    and bool("".join(self._current_output).strip())
                    and not _has_interrupt_hint(self._last_terminal_snapshot)
                    and (time.monotonic() - self._last_output_at) >= SILENCE_TIMEOUT_SECONDS
                )
                turn_expired = (
                    self._current_message is not None
                    and self._pending_interaction is None
                    and self._current_started_at > 0
                    and (time.monotonic() - self._current_started_at) >= MAX_TURN_SECONDS
                )
            if timed_out or turn_expired:
                if self._detect_interaction(interaction_text):
                    continue
                self._finalize_current()

    # ------------------------------------------------------------------ api
    def enqueue_message(
        self,
        text: str,
        *,
        reply_to_leader: str | None = None,
        delegation_id: str | None = None,
        assignment_id: str | None = None,
        summarize_delegation_id: str | None = None,
    ) -> None:
        item = {
            "id": f"job_{next(self._counter):04d}",
            "text": text,
            "reply_to_leader": reply_to_leader,
            "delegation_id": delegation_id,
            "assignment_id": assignment_id,
            "summarize_delegation_id": summarize_delegation_id,
        }
        with self._lock:
            self._queue.append(item)
            current_busy = self._current_message is not None or self._pending_interaction is not None
        store.update_agent(
            self.agent_id,
            status="busy",
            current_task="等待队列执行" if current_busy else "准备处理消息",
            interaction_state="queued",
        )
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
        self._send_terminal_data(data)
        self._track_terminal_interaction_data(data)

    def resize_terminal(self, rows: int, columns: int) -> None:
        self._resize_terminal(rows, columns)

    def close(self) -> None:
        self._closed = True
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


class ACPPool:
    """Compatibility wrapper kept under the old module path/import name."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.clients: dict[str, HermesSession] = {}

    def is_running(self, agent_id: str) -> bool:
        with self._lock:
            session = self.clients.get(agent_id)
        return bool(session and session.proc.isalive())

    def start(self, agent: dict) -> bool:
        agent_id = agent["agent_id"]
        profile_name = agent["profile_name"]
        pending_items: list[dict[str, Any]] = []
        with self._lock:
            existing = self.clients.get(agent_id)
            if existing and existing.proc.isalive():
                return True
            if existing is not None:
                pending_items = existing.take_pending_messages()
        try:
            session = HermesSession(profile_name, agent_id, self._on_final)
        except FileNotFoundError:
            store.update_agent(
                agent_id,
                runtime_status="crashed",
                interaction_state="failed",
                status="offline",
            )
            store.push_event(
                "agent.runtime.failed",
                agent_id,
                None,
                {"text": "hermes CLI not found in PATH"},
            )
            return False
        except Exception as exc:  # noqa: BLE001
            store.update_agent(
                agent_id,
                runtime_status="crashed",
                interaction_state="failed",
                status="offline",
            )
            store.push_event(
                "agent.runtime.failed",
                agent_id,
                None,
                {"text": f"failed to start Hermes session: {exc}"},
            )
            return False
        with self._lock:
            self.clients[agent_id] = session
        session.restore_pending_messages(pending_items)
        store.update_agent(
            agent_id,
            runtime_status="running",
            interaction_state="idle",
            pending_interaction=None,
            status="idle",
            current_task="空闲",
        )
        store.push_event(
            "agent.runtime.started",
            agent_id,
            None,
            {"text": f"Hermes session 已启动（profile={profile_name}）"},
        )
        return True

    def stop(self, agent_id: str) -> None:
        with self._lock:
            session = self.clients.pop(agent_id, None)
        if session is not None:
            session.close()
        store.update_agent(
            agent_id,
            runtime_status="stopped",
            interaction_state="idle",
            pending_interaction=None,
            queue_depth=0,
            status="offline",
            current_task="已停止",
        )
        store.push_event(
            "agent.runtime.stopped",
            agent_id,
            None,
            {"text": "Hermes session 已停止"},
        )

    def prompt(
        self,
        agent_id: str,
        content: str,
        *,
        reply_to_leader: str | None = None,
        delegation_id: str | None = None,
        assignment_id: str | None = None,
        summarize_delegation_id: str | None = None,
    ) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        session.enqueue_message(
            content,
            reply_to_leader=reply_to_leader,
            delegation_id=delegation_id,
            assignment_id=assignment_id,
            summarize_delegation_id=summarize_delegation_id,
        )

    def respond_interaction(self, agent_id: str, request_id: str, response: str) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        session.respond_interaction(request_id, response)

    def send_terminal_input(self, agent_id: str, text: str) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        session.send_terminal_input(text)

    def send_terminal_data(self, agent_id: str, data: str) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        session.send_terminal_data(data)

    def resize_terminal(self, agent_id: str, rows: int, columns: int) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        session.resize_terminal(rows, columns)

    def _on_final(
        self,
        agent_id: str,
        reply: str,
        leader_id: str | None,
        delegation_id: str | None,
        assignment_id: str | None,
        summarize_delegation_id: str | None,
    ) -> None:
        if summarize_delegation_id:
            try:
                store.mark_delegation_summarized(summarize_delegation_id)
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "delegation.summary.failed",
                    agent_id,
                    summarize_delegation_id,
                    {"text": f"标记批次总结完成失败：{exc}"},
                )
        if leader_id and delegation_id and assignment_id:
            try:
                completed = store.complete_assignment(
                    delegation_id,
                    assignment_id,
                    result=reply or "(空响应)",
                )
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "delegation.assignment.failed",
                    agent_id,
                    delegation_id,
                    {"text": f"记录 worker 结果失败：{exc}"},
                )
                completed = None
            if completed:
                self._prompt_leader_to_summarize(completed)
            return
        if leader_id:
            worker = store.find_agent(agent_id) or {}
            name = worker.get("name") or agent_id
            try:
                self.prompt(leader_id, f"[来自 {name} 的回复]: {reply}")
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "agent.output.failed",
                    leader_id,
                    None,
                    {"text": f"回推 leader 失败：{exc}"},
                )

    def _prompt_leader_to_summarize(self, delegation: dict) -> None:
        leader_id = delegation["leader_agent_id"]
        delegation_id = delegation["delegation_id"]
        store.mark_delegation_summarizing(delegation_id)
        results = []
        for index, assignment in enumerate(delegation["assignments"], start=1):
            results.append(
                "\n".join(
                    [
                        f"## {index}. {assignment['worker_name']} ({assignment['worker_agent_id']})",
                        f"子任务：{assignment['content']}",
                        f"状态：{assignment['status']}",
                        "结果：",
                        assignment.get("result") or "(空响应)",
                    ]
                )
            )
        worker_results = "\n\n".join(results)
        prompt = (
            "[SYSTEM_DELEGATION_SUMMARY_REQUEST]\n"
            f"delegation_id: {delegation_id}\n"
            "同一批 worker 子任务已经全部结束。请只基于以下 worker 结果，面向用户输出最终总结。\n"
            "不要再次派发同一批任务；如有缺失或失败，请在总结中明确说明。\n\n"
            "总结要求：\n"
            f"{delegation['summary_instruction']}\n\n"
            "Worker 结果：\n"
            f"{worker_results}"
        )
        try:
            self.prompt(
                leader_id,
                prompt,
                summarize_delegation_id=delegation_id,
            )
        except Exception as exc:  # noqa: BLE001
            store.push_event(
                "agent.output.failed",
                leader_id,
                delegation_id,
                {"text": f"回推 leader 汇总请求失败：{exc}"},
            )

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self.clients.keys())
        for agent_id in ids:
            self.stop(agent_id)


pool = ACPPool()
