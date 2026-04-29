from app.services.acp import STUCK_HINT_SECONDS, _extract_selection, _looks_ready_for_next_input, _should_show_stuck_hint


def test_ready_prompt_without_symbol_is_detected():
    assert _looks_ready_for_next_input("leader ❯")


def test_ready_prompt_with_symbol_is_detected():
    assert _looks_ready_for_next_input("dev Ψ ❯")


def test_stuck_hint_waits_for_threshold():
    assert not _should_show_stuck_hint(
        active=True,
        pending_interaction=False,
        started_at=100.0,
        last_output_at=200.0,
        hint_sent=False,
        now=200.0 + STUCK_HINT_SECONDS - 1,
    )


def test_stuck_hint_does_not_repeat():
    assert not _should_show_stuck_hint(
        active=True,
        pending_interaction=False,
        started_at=100.0,
        last_output_at=200.0,
        hint_sent=True,
        now=200.0 + STUCK_HINT_SECONDS,
    )


def test_stuck_hint_after_threshold():
    assert _should_show_stuck_hint(
        active=True,
        pending_interaction=False,
        started_at=100.0,
        last_output_at=200.0,
        hint_sent=False,
        now=200.0 + STUCK_HINT_SECONDS,
    )


def test_selection_parser_uses_latest_input_prompt():
    text = """
╭─ Hermes needs your input ─╮
│ ❯ 1. 开发（agent_dev）      │
│   2. 开发者（agent_dev1）  │
╰───────────────────────────╯

⚡ mcp_agent_bus_send_to_worker  (0.0s)

╭─ Hermes needs your input ─╮
│   1. 开发（agent_dev）      │
│ ❯ 2. 开发者（agent_dev1）  │
╰───────────────────────────╯
"""

    selection = _extract_selection(text)

    assert selection == {
        "choices": ["1. 开发（agent_dev）", "2. 开发者（agent_dev1）"],
        "selected_index": 1,
    }


def test_selection_parser_ignores_stale_choice_fragments_without_prompt():
    text = """
  3. Other (type your answer)
  1. 开发（agent_dev）
❯ 2. 开发者（agent_dev1）
⚡ mcp_agent_bus_send_to_worker  (0.0s)
leader ❯
"""

    assert _extract_selection(text) is None
