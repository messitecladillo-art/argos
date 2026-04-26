"""Per-agent persistent `hermes -p <profile>` session pool powered by pexpect.

Each HermesSession owns one interactive Hermes CLI process. Messages are queued
per agent to preserve session context. Output is streamed into the RuntimeStore,
and basic human-in-the-loop approvals/inputs are detected from terminal text.
"""
from __future__ import annotations

import os
import re
import logging
import threading
import time
from collections import deque
from itertools import count
from typing import Any
from uuid import uuid4

import pexpect
import pyte

from ..models.store import store


logger = logging.getLogger("hermes.agent_state")

SILENCE_TIMEOUT_SECONDS = 10.0
MAX_TURN_SECONDS = 120.0
READ_CHUNK_SIZE = 1024
READ_LOOP_INTERVAL = 0.2
MAX_RAW_OUTPUT_CHARS = 12000
TERMINAL_COLUMNS = 120
TERMINAL_LINES = 36
RESOLVED_INTERACTION_SUPPRESS_SECONDS = 30.0

READY_PATTERNS = (
    re.compile(r"(?m)^\s*(?:[\w.-]+\s+)?(?:⚕\s*)?❯\s*$"),
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
    text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b\[[0-9;?: ]*[A-Za-z~]", "", text)
    text = re.sub(r"\x1b[()#][0-9A-Za-z]", "", text)
    return re.sub(r"\x1b.", "", text)


def _is_tui_noise_line(value: str) -> bool:
    if not value:
        return False
    if re.fullmatch(r"[\s\-─━═│┃║┌┐└┘┏┓┗┛╭╮╰╯├┤┬┴┼╞╡╪╥╨╔╗╚╝╠╣╦╩╬]+", value):
        return True
    if re.fullmatch(r"[Jj0-9]{1,3}", value):
        return True
    if re.search(r"\bgpt-[\w.-]+\b.*\[[█░▒▓\s]+\].*\d+%", value, re.IGNORECASE):
        return True
    if "Hermes" in value and re.search(r"[─━═╭╮╰╯┌┐└┘]", value):
        return True
    if "type a message + Enter to interrupt" in value:
        return True
    if "cursor position requests" in value.lower():
        return True
    if re.fullmatch(r"[\w.-]+\s+❯", value):
        return True
    if re.fullmatch(r"[⚕$]\s*❯.*", value):
        return True
    return False


def _clean_agent_reply(text: str) -> str:
    text = _strip_ansi(text).replace("\r", "\n")
    cleaned: list[str] = []
    previous_blank = False
    for raw_line in text.splitlines():
        value = raw_line.strip()
        if _is_tui_noise_line(value):
            continue
        if not value:
            if cleaned and not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue
        cleaned.append(value)
        previous_blank = False
    return "\n".join(cleaned).strip()


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


def _looks_ready_for_next_input(*texts: str) -> bool:
    return any(
        pattern.search(text)
        for text in texts
        if text
        for pattern in READY_PATTERNS
    )


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


def _log_state(event: str, agent_id: str, **fields: Any) -> None:
    details = " ".join(f"{key}={value!r}" for key, value in fields.items())
    logger.warning("[agent-state] %s agent=%s %s", event, agent_id, details)


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
        self._current_had_interrupt_hint = False
        self._current_saw_substantive_output = False
        self._manual_terminal_active = False
        self._manual_terminal_user_task_id: str | None = None
        self._manual_terminal_buffer = ""
        self._manual_terminal_output: list[str] = []
        self._manual_terminal_started_at = 0.0
        self._manual_terminal_had_interrupt_hint = False
        self._manual_terminal_saw_substantive_output = False
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
            current_user_task_id = None
            if self._current_message is not None:
                queue_depth += 1
                current_user_task_id = self._current_message.get("user_task_id")
        queue_depth += store.count_active_user_tasks(
            self.agent_id,
            exclude_user_task_id=current_user_task_id,
        )
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
                active_tasks = store.count_active_user_tasks(self.agent_id)
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
                return
            message = self._queue.popleft()
            self._current_message = message
            self._current_output = []
            self._current_had_interrupt_hint = False
            self._current_saw_substantive_output = False
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
        active_tasks = store.count_active_user_tasks(
            self.agent_id,
            exclude_user_task_id=message.get("user_task_id"),
        )
        next_state = "queued" if self._queue or active_tasks else "idle"
        next_status = "busy" if self._queue or active_tasks else "idle"
        agent = store.find_agent(self.agent_id) or {}
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
                    self._last_output_at = now
            manual_active = self._manual_terminal_active and not running
            if manual_active:
                self._manual_terminal_output.append(clean)
                if _has_interrupt_hint(clean) or _has_interrupt_hint(terminal_snapshot):
                    self._manual_terminal_had_interrupt_hint = True
                if _is_substantive_output(clean):
                    self._manual_terminal_saw_substantive_output = True
                    self._last_output_at = now
            pending = self._pending_interaction
            current_text = "".join(self._current_output)[-2000:]
            current_had_interrupt_hint = self._current_had_interrupt_hint
            current_saw_substantive_output = self._current_saw_substantive_output
            manual_text = "".join(self._manual_terminal_output)[-2000:]
            manual_had_interrupt_hint = self._manual_terminal_had_interrupt_hint
            manual_saw_substantive_output = self._manual_terminal_saw_substantive_output

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
                _log_state("running_from_chunk", self.agent_id, chunk_len=len(chunk))

        if pending is not None:
            return

        recent = self._tail(2000)
        detection_text = f"{terminal_snapshot}\n{recent}"
        if not running:
            if self._detect_interaction(detection_text):
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
        if self._detect_interaction(detection_text):
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
                manual_timed_out = (
                    self._manual_terminal_active
                    and self._current_message is None
                    and self._pending_interaction is None
                    and bool("".join(self._manual_terminal_output).strip())
                    and not _has_interrupt_hint(self._last_terminal_snapshot)
                    and (time.monotonic() - self._last_output_at) >= SILENCE_TIMEOUT_SECONDS
                )
                manual_turn_expired = (
                    self._manual_terminal_active
                    and self._current_message is None
                    and self._pending_interaction is None
                    and self._manual_terminal_started_at > 0
                    and (time.monotonic() - self._manual_terminal_started_at) >= MAX_TURN_SECONDS
                )
            if timed_out or turn_expired:
                if self._detect_interaction(interaction_text):
                    continue
                _log_state(
                    "timeout_finalize",
                    self.agent_id,
                    timed_out=timed_out,
                    turn_expired=turn_expired,
                    idle_for=round(time.monotonic() - self._last_output_at, 2),
                )
                self._finalize_current()
            if manual_timed_out or manual_turn_expired:
                if self._detect_interaction(interaction_text):
                    continue
                _log_state(
                    "terminal_manual_timeout_finalize",
                    self.agent_id,
                    timed_out=manual_timed_out,
                    turn_expired=manual_turn_expired,
                    idle_for=round(time.monotonic() - self._last_output_at, 2),
                )
                self._finalize_manual_terminal()

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
        user_task_id: str | None = None,
        summarize_delegation_id: str | None = None,
        summarize_user_task_id: str | None = None,
    ) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        _log_state(
            "pool_prompt",
            agent_id,
            delegation_id=delegation_id,
            assignment_id=assignment_id,
            user_task_id=user_task_id,
            summarize_user_task_id=summarize_user_task_id,
        )
        session.enqueue_message(
            content,
            reply_to_leader=reply_to_leader,
            delegation_id=delegation_id,
            assignment_id=assignment_id,
            user_task_id=user_task_id,
            summarize_delegation_id=summarize_delegation_id,
            summarize_user_task_id=summarize_user_task_id,
        )

    def current_user_task_id(self, agent_id: str) -> str | None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            return None
        return session.current_user_task_id()

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
        user_task_id: str | None,
        summarize_delegation_id: str | None,
        summarize_user_task_id: str | None,
        failed: bool = False,
    ) -> None:
        if summarize_user_task_id:
            _log_state("summary_final", agent_id, user_task_id=summarize_user_task_id, reply_len=len(reply or ""))
            try:
                store.mark_user_task_completed(summarize_user_task_id)
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "user_task.summary.failed",
                    agent_id,
                    summarize_user_task_id,
                    {"text": f"标记用户任务总结完成失败：{exc}"},
                )
            return
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
            _log_state(
                "assignment_final",
                agent_id,
                delegation_id=delegation_id,
                assignment_id=assignment_id,
                user_task_id=user_task_id,
                failed=failed,
                reply_len=len(reply or ""),
            )
            try:
                completed = store.complete_assignment(
                    delegation_id,
                    assignment_id,
                    result=reply or "(空响应)",
                    failed=failed,
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
                if completed.get("user_task_id"):
                    self._prompt_user_task_to_summarize(completed)
                else:
                    self._prompt_leader_to_summarize(completed)
            return
        if user_task_id:
            _log_state("user_task_dispatch_final", agent_id, user_task_id=user_task_id, reply_len=len(reply or ""))
            try:
                completed = store.close_user_task_dispatch(user_task_id)
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "user_task.dispatch.failed",
                    agent_id,
                    user_task_id,
                    {"text": f"关闭用户任务派发阶段失败：{exc}"},
                )
                completed = None
            if completed:
                self._prompt_user_task_to_summarize(completed)
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

    def _prompt_user_task_to_summarize(self, user_task: dict) -> None:
        user_task_id = user_task["user_task_id"]
        user_task = store.mark_user_task_summarizing(user_task_id)
        leader_id = user_task["leader_agent_id"]
        results = []
        for delegation in store.snapshot()["delegations"]:
            if delegation.get("user_task_id") != user_task_id:
                continue
            for index, assignment in enumerate(delegation["assignments"], start=1):
                results.append(
                    "\n".join(
                        [
                            f"## {len(results) + 1}. {assignment['worker_name']} ({assignment['worker_agent_id']})",
                            f"批次：{delegation['delegation_id']}",
                            f"子任务：{assignment['content']}",
                            f"状态：{assignment['status']}",
                            "结果：",
                            assignment.get("result") or "(空响应)",
                        ]
                    )
                )
        worker_results = "\n\n".join(results) or "(没有 worker 结果)"
        prompt = (
            "[SYSTEM_USER_TASK_SUMMARY_REQUEST]\n"
            f"user_task_id: {user_task_id}\n"
            "同一个用户任务拆分出的所有 worker 子任务已经全部结束。请只基于以下 worker 结果，面向用户输出最终总结。\n"
            "不要再次派发同一批任务；如有缺失或失败，请在总结中明确说明。\n\n"
            "用户原始任务：\n"
            f"{user_task.get('content') or ''}\n\n"
            "Worker 结果：\n"
            f"{worker_results}"
        )
        try:
            self.prompt(
                leader_id,
                prompt,
                summarize_user_task_id=user_task_id,
            )
        except Exception as exc:  # noqa: BLE001
            store.push_event(
                "agent.output.failed",
                leader_id,
                user_task_id,
                {"text": f"回推 leader 用户任务汇总请求失败：{exc}"},
            )

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self.clients.keys())
        for agent_id in ids:
            self.stop(agent_id)


pool = ACPPool()
