from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _alembic_cfg(db_path: str) -> Config:
    cfg = Config(str(Path("argos/db/migrations/alembic.ini").resolve()))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _engine(db_path: str):
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )


def test_alembic_upgrade_creates_all_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    command.upgrade(_alembic_cfg(db_path), "head")

    inspector = inspect(_engine(db_path))
    tables = sorted(inspector.get_table_names())
    expected = [
        "ab_experiments", "agent_mcp_servers", "agent_skill_installs",
        "agents", "assignments", "delegations", "events",
        "execution_traces", "feedback_signals", "kanban_task_links",
        "learning_suggestions", "memory_items", "messages",
        "model_configs", "settings", "user_tasks",
    ]
    for table in expected:
        assert table in tables, f"Missing table: {table}"


def test_alembic_downgrade_removes_all_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    cfg = _alembic_cfg(db_path)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    inspector = inspect(_engine(db_path))
    tables = [t for t in inspector.get_table_names() if t != "alembic_version"]
    assert len(tables) == 0, f"Tables remain after downgrade: {tables}"


def test_upgrade_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    cfg = _alembic_cfg(db_path)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")

    inspector = inspect(_engine(db_path))
    tables = [t for t in inspector.get_table_names() if t != "alembic_version"]
    assert len(tables) == 16


def test_user_tasks_has_required_columns(tmp_path):
    db_path = str(tmp_path / "test.db")
    command.upgrade(_alembic_cfg(db_path), "head")

    engine = _engine(db_path)
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(user_tasks)"))}
    required = {"current_round", "max_rounds", "review_task_ids_json", "blocked_at", "block_reason"}
    assert required <= columns, f"Missing columns: {required - columns}"


def test_pre_alembic_db_is_stamped(tmp_path):
    """A database with tables but no alembic_version gets stamped before upgrade."""
    db_path = str(tmp_path / "pre_alembic.db")
    engine = _engine(db_path)
    # Simulate pre-Alembic schema by creating tables directly
    from argos.db.session import Base
    Base.metadata.create_all(bind=engine)

    # Verify tables exist but no alembic_version
    inspector = inspect(engine)
    tables_before = inspector.get_table_names()
    assert len(tables_before) > 0
    assert "alembic_version" not in tables_before
    engine.dispose()

    # Use Alembic to stamp the existing DB directly
    cfg = _alembic_cfg(db_path)
    from alembic import command
    command.stamp(cfg, "2ce2d98a3fc5")

    # Verify alembic_version now exists with the stamped revision
    engine2 = _engine(db_path)
    with engine2.connect() as conn:
        rows = conn.execute(
            __import__("sqlalchemy").text("SELECT version_num FROM alembic_version")
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "2ce2d98a3fc5"

    # Running upgrade on a stamped DB should be idempotent
    command.upgrade(cfg, "head")
    inspector2 = inspect(engine2)
    tables_after = inspector2.get_table_names()
    for table in tables_before:
        assert table in tables_after, f"Missing table after upgrade: {table}"


def test_execution_traces_has_consolidated_column(tmp_path):
    db_path = str(tmp_path / "test.db")
    command.upgrade(_alembic_cfg(db_path), "head")

    engine = _engine(db_path)
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(execution_traces)"))}
    assert "consolidated" in columns
