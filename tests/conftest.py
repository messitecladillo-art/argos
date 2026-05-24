"""Pytest configuration — initializes the learning system at module level.

When run via `python tests/test_learning_smoke.py`, the main() function
does the same setup. This module runs during pytest collection so tests
discovered by pytest work identically.
"""

from __future__ import annotations

import os
import sys
import tempfile

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Switch to temp DB so tests never touch production data
_temp_db = os.path.join(tempfile.mkdtemp(prefix="hermes_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_temp_db}"
os.environ["LEARN_EMBED_PROVIDER"] = "dummy"  # no Ollama needed for tests
os.environ["FLASK_DEBUG"] = "1"  # suppress SECRET_KEY warning in tests

from app.db import init_database  # noqa: E402
from app.learning import (  # noqa: E402
    ab_evaluator,
    active_engine,
    feedback_engine,
    memory_store,
    trace_collector,
)
from app.models.store import store  # noqa: E402

init_database()
store.load_persisted_state()
trace_collector.init_app(store)
memory_store.init_app(store)
feedback_engine.init_app(store, memory_store)
active_engine.init_app(store, memory_store)
ab_evaluator.init_app(store)
