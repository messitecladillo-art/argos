from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_runtime_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        _ensure_columns(
            connection,
            "user_tasks",
            {
                "current_round": "INTEGER DEFAULT 1",
                "max_rounds": "INTEGER DEFAULT 10",
                "review_task_ids_json": "TEXT DEFAULT '[]'",
                "blocked_at": "VARCHAR(40) NULL",
                "block_reason": "TEXT DEFAULT ''",
            },
        )
        _ensure_columns(
            connection,
            "delegations",
            {
                "round": "INTEGER DEFAULT 1",
                "review_task_id": "VARCHAR(120) NULL",
                "reviewed_at": "VARCHAR(40) NULL",
            },
        )


def _ensure_columns(connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {
        row[1]
        for row in connection.execute(text(f"PRAGMA table_info({table_name})"))
    }
    for column_name, definition in columns.items():
        if column_name in existing:
            continue
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
