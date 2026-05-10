from __future__ import annotations

from sqlalchemy import create_engine, text

from app.db.migrations import ensure_runtime_schema


def test_ensure_runtime_schema_adds_long_running_task_columns(tmp_path):
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE user_tasks (
                    id INTEGER PRIMARY KEY,
                    user_task_id VARCHAR(80),
                    leader_agent_id VARCHAR(120),
                    content TEXT,
                    delegation_ids_json TEXT,
                    status VARCHAR(60),
                    dispatch_closed BOOLEAN,
                    summary_requested_at VARCHAR(40),
                    completed_at VARCHAR(40)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE delegations (
                    id INTEGER PRIMARY KEY,
                    delegation_id VARCHAR(80),
                    user_task_id VARCHAR(80),
                    leader_agent_id VARCHAR(120),
                    summary_instruction TEXT,
                    status VARCHAR(60),
                    completed_at VARCHAR(40),
                    summarized_at VARCHAR(40)
                )
                """
            )
        )

    ensure_runtime_schema(engine)

    with engine.connect() as connection:
        user_task_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(user_tasks)"))}
        delegation_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(delegations)"))}

    assert {"current_round", "max_rounds", "review_task_ids_json", "blocked_at", "block_reason"} <= user_task_columns
    assert {"round", "review_task_id", "reviewed_at"} <= delegation_columns
