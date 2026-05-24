from __future__ import annotations

from pathlib import Path


def test_human_input_card_click_opens_answer_flow_instead_of_terminal():
    source = Path("argos/static/app.js").read_text(encoding="utf-8")

    assert "function openKanbanTask(link)" in source
    assert "kanbanTaskCanAnswer(link)" in source
    assert "answerHumanInputTask(link)" in source
    assert "card.addEventListener(\"click\", () => openKanbanTask(link))" in source
    assert "link?.kanban_role === \"human_input\"" in source
    assert "!KANBAN_TERMINAL_STATUSES.has(String(link?.kanban_status || \"\").toLowerCase())" in source
