"""Module-level constants and pure helper functions for the ACP package.

Separated from HermesSession/ACPPool so terminal text parsing, ANSI
normalization, selection extraction and readiness detection can be imported
(and tested) without spinning up a pexpect session.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import pyte


logger = logging.getLogger("hermes.agent_state")

CONCISE_SUMMARY_RULES = (
    "输出要求：先给结论，保持简洁；普通总结控制在 8 行以内，优先使用 3-5 条要点。\n"
    "只保留用户需要的关键结果、风险/阻塞和下一步；不要复述完整 worker 原文。\n"
    "除非用户明确要求详细说明，否则不要长篇展开。\n"
)

STUCK_HINT_SECONDS = 300.0
READ_CHUNK_SIZE = 1024
READ_LOOP_INTERVAL = 0.2
MAX_RAW_OUTPUT_CHARS = 12000
MAX_TERMINAL_BUFFER_CHARS = 64000
MAX_TERMINAL_SUBSCRIBER_QUEUE = 256
TERMINAL_QUEUE_CLOSE_SENTINEL = {"type": "__close__"}
TERMINAL_COLUMNS = 120
TERMINAL_LINES = 36
RESOLVED_INTERACTION_SUPPRESS_SECONDS = 30.0

READY_PATTERNS = (
    re.compile(r"(?m)^\s*(?:[\w.-]+\s+)?(?:\S+\s+)?❯\s*$"),
    re.compile(r"(?m)^\s*[\w.-]+\s+[Ψψ>]\s*$"),
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


def _char_style_sgr(char: Any) -> str:
    fg_map = {
        "black": 30,
        "red": 31,
        "green": 32,
        "brown": 33,
        "blue": 34,
        "magenta": 35,
        "cyan": 36,
        "white": 37,
        "default": 39,
    }
    bg_map = {
        "black": 40,
        "red": 41,
        "green": 42,
        "brown": 43,
        "blue": 44,
        "magenta": 45,
        "cyan": 46,
        "white": 47,
        "default": 49,
    }
    codes = [
        1 if getattr(char, "bold", False) else 22,
        3 if getattr(char, "italics", False) else 23,
        4 if getattr(char, "underscore", False) else 24,
        5 if getattr(char, "blink", False) else 25,
        7 if getattr(char, "reverse", False) else 27,
        9 if getattr(char, "strikethrough", False) else 29,
        fg_map.get(getattr(char, "fg", "default"), 39),
        bg_map.get(getattr(char, "bg", "default"), 49),
    ]
    return f"\x1b[{';'.join(str(code) for code in codes)}m"


def _is_default_char(char: Any) -> bool:
    return (
        getattr(char, "data", " ") == " "
        and getattr(char, "fg", "default") == "default"
        and getattr(char, "bg", "default") == "default"
        and not getattr(char, "bold", False)
        and not getattr(char, "italics", False)
        and not getattr(char, "underscore", False)
        and not getattr(char, "strikethrough", False)
        and not getattr(char, "reverse", False)
        and not getattr(char, "blink", False)
    )


def _screen_to_ansi(screen: pyte.Screen) -> str:
    default_char = pyte.screens.Char(" ")
    rows: list[str] = []
    last_non_empty_row = -1

    for row_index in range(screen.lines):
        row = screen.buffer.get(row_index)
        if row is None:
            rows.append("")
            continue
        last_non_empty_col = -1
        for col_index in range(screen.columns):
            char = row.get(col_index, default_char)
            if not _is_default_char(char):
                last_non_empty_col = col_index
        if last_non_empty_col < 0:
            rows.append("")
            continue

        parts: list[str] = []
        current_style: str | None = None
        for col_index in range(last_non_empty_col + 1):
            char = row.get(col_index, default_char)
            style = _char_style_sgr(char)
            if style != current_style:
                parts.append(style)
                current_style = style
            parts.append(getattr(char, "data", " "))
        if current_style is not None:
            parts.append("\x1b[0m")
        rows.append("".join(parts))
        last_non_empty_row = row_index

    visible_rows = rows[: last_non_empty_row + 1]
    body = "\r\n".join(visible_rows)
    cursor_y = max(0, min(int(getattr(screen.cursor, "y", 0)), screen.lines - 1))
    cursor_x = max(0, min(int(getattr(screen.cursor, "x", 0)), screen.columns - 1))
    cursor_seq = f"\x1b[{cursor_y + 1};{cursor_x + 1}H"
    return f"\x1b[0m\x1b[2J\x1b[H{body}\x1b[0m{cursor_seq}"


def _terminal_ansi_count(text: str) -> int:
    return len(
        re.findall(
            r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-Z\\-_])",
            text,
        )
    )


def _terminal_control_codes(text: str) -> list[int]:
    codes: list[int] = []
    for char in text:
        code = ord(char)
        if (code < 32 and char not in "\n\r\t\x1b") or code == 127:
            codes.append(code)
    return codes


def _terminal_preview(text: str, limit: int = 180) -> str:
    snippet = text[:limit]
    return snippet.encode("unicode_escape", "backslashreplace").decode("ascii")


def _is_suspicious_terminal_text(text: str) -> bool:
    if not text:
        return False
    if "�" in text:
        return True
    return bool(_terminal_control_codes(text))


def _log_terminal_debug(event: str, agent_id: str, text: str, **fields: Any) -> None:
    controls = _terminal_control_codes(text)
    payload = {
        "len": len(text),
        "ansi": _terminal_ansi_count(text),
        "controls": controls[:12],
        "has_replacement": "�" in text,
        "preview": _terminal_preview(text),
        **fields,
    }
    details = " ".join(f"{key}={value!r}" for key, value in payload.items())
    logger.warning("[terminal-debug] %s agent=%s %s", event, agent_id, details)


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


def _should_show_stuck_hint(
    *,
    active: bool,
    pending_interaction: bool,
    started_at: float,
    last_output_at: float,
    hint_sent: bool,
    now: float,
) -> bool:
    return (
        active
        and not pending_interaction
        and not hint_sent
        and started_at > 0
        and (now - max(started_at, last_output_at)) >= STUCK_HINT_SECONDS
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

    raw_lines = text.splitlines()
    prompt_start = None
    for index, line in enumerate(raw_lines):
        if re.search(r"\bHermes needs your input\b", line, re.IGNORECASE):
            prompt_start = index
    if prompt_start is not None:
        raw_lines = raw_lines[prompt_start:]
    lines = [_clean_selection_line(line) for line in raw_lines]
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


def _has_active_selection_prompt(text: str) -> bool:
    return _extract_selection(text) is not None


def _interaction_signature(kind: str, choices: list[str] | None = None, prompt: str = "") -> str:
    if choices:
        return f"{kind}:" + "|".join(_clean_choice_label(choice) for choice in choices)
    compact_prompt = re.sub(r"\s+", " ", _strip_ansi(prompt))[-240:]
    return f"{kind}:{compact_prompt}"


def _log_state(event: str, agent_id: str, **fields: Any) -> None:
    details = " ".join(f"{key}={value!r}" for key, value in fields.items())
    logger.warning("[agent-state] %s agent=%s %s", event, agent_id, details)
