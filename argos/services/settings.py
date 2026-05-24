from __future__ import annotations

from ..config import KANBAN_AUTO_DISPATCH
from ..db import SQLitePersistence

KANBAN_AUTO_DISPATCH_KEY = "kanban_auto_dispatch_enabled"


def _bool_to_setting(value: bool) -> str:
    return "1" if value else "0"


def _setting_to_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value == "1"


class SettingsService:
    def __init__(self, persistence: SQLitePersistence | None = None) -> None:
        self.persistence = persistence or SQLitePersistence()

    def get_kanban_auto_dispatch_enabled(self) -> bool:
        return _setting_to_bool(
            self.persistence.get_setting(KANBAN_AUTO_DISPATCH_KEY),
            default=KANBAN_AUTO_DISPATCH,
        )

    def set_kanban_auto_dispatch_enabled(self, enabled: bool) -> bool:
        self.persistence.set_setting(KANBAN_AUTO_DISPATCH_KEY, _bool_to_setting(enabled))
        return enabled


settings_service = SettingsService()
