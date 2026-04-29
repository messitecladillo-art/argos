from app.services.acp import STUCK_HINT_SECONDS, _looks_ready_for_next_input, _should_show_stuck_hint


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
