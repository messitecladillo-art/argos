"""ACP package — re-exports of the previous flat `acp.py` public surface.

Existing call sites rely on importing names like `pool`,
`TERMINAL_QUEUE_CLOSE_SENTINEL`, `STUCK_HINT_SECONDS`, and a handful of
helpers from `argos.services.acp`. This module preserves those imports while
the implementation is split across `helpers.py`, `session.py`, `pool.py`.
"""
from __future__ import annotations

from .helpers import (
    CONCISE_SUMMARY_RULES,
    MAX_RAW_OUTPUT_CHARS,
    MAX_TERMINAL_BUFFER_CHARS,
    MAX_TERMINAL_SUBSCRIBER_QUEUE,
    READ_CHUNK_SIZE,
    READ_LOOP_INTERVAL,
    RESOLVED_INTERACTION_SUPPRESS_SECONDS,
    STUCK_HINT_SECONDS,
    TERMINAL_COLUMNS,
    TERMINAL_LINES,
    TERMINAL_QUEUE_CLOSE_SENTINEL,
    _clean_agent_reply,
    _clean_choice_label,
    _clean_selection_line,
    _compact_screen_text,
    _extract_selection,
    _has_active_selection_prompt,
    _has_interrupt_hint,
    _interaction_signature,
    _is_non_interaction_text,
    _is_substantive_output,
    _is_suspicious_terminal_text,
    _is_tui_noise_line,
    _log_state,
    _log_terminal_debug,
    _looks_ready_for_next_input,
    _screen_to_ansi,
    _should_show_stuck_hint,
    _strip_ansi,
    _terminal_ansi_count,
    _terminal_control_codes,
    _terminal_preview,
    logger,
)
from .pool import ACPPool, pool
from .session import HermesSession


__all__ = [
    "ACPPool",
    "HermesSession",
    "STUCK_HINT_SECONDS",
    "TERMINAL_QUEUE_CLOSE_SENTINEL",
    "_extract_selection",
    "_looks_ready_for_next_input",
    "_should_show_stuck_hint",
    "pool",
]
