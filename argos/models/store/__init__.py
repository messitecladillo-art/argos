"""Public RuntimeStore — composed from feature mixins.

Existing imports (`from argos.models.store import RuntimeStore, store`) keep
working unchanged; the implementation is now split across submodules in
this package.
"""
from __future__ import annotations

from ...db import SQLitePersistence
from .agents import AgentsMixin
from .base import (
    NON_PERSISTED_EVENT_TYPES,
    RuntimeStoreBase,
    _log_store,
    logger,
)
from .delegations import DelegationsMixin
from .events import EventsMixin
from .kanban import KanbanLinksMixin
from .learning import LearningMixin
from .messages import MessagesMixin
from .user_tasks import UserTasksMixin


class RuntimeStore(
    AgentsMixin,
    UserTasksMixin,
    DelegationsMixin,
    KanbanLinksMixin,
    LearningMixin,
    MessagesMixin,
    EventsMixin,
    RuntimeStoreBase,
):
    pass


store = RuntimeStore(SQLitePersistence())


__all__ = [
    "NON_PERSISTED_EVENT_TYPES",
    "RuntimeStore",
    "RuntimeStoreBase",
    "logger",
    "store",
]
