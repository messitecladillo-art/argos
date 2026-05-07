from __future__ import annotations

import logging

from ..config import AUTO_START_AGENTS
from ..models.store import store
from .acp import pool as session_pool

logger = logging.getLogger(__name__)


def start_ready_agents_on_boot() -> None:
    if not AUTO_START_AGENTS:
        logger.info("agent auto-start disabled by AUTO_START_AGENTS=0")
        return

    for agent in store.snapshot().get("agents", []):
        agent_id = agent.get("agent_id")
        if (agent.get("readiness_status") or "ready") != "ready":
            logger.info("skip auto-start for not-ready agent %s", agent_id)
            continue
        if (agent.get("runtime_status") or "stopped") == "running" and session_pool.is_running(agent_id):
            continue
        try:
            session_pool.start(agent)
        except Exception:  # noqa: BLE001
            logger.exception("failed to auto-start agent %s", agent_id)
