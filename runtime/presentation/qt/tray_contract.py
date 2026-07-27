from __future__ import annotations

from dataclasses import dataclass


OPEN_TEXT = "فتح"
LOGOUT_TEXT = "تسجيل الخروج"
EXIT_TEXT = "إغلاق"


@dataclass(frozen=True, slots=True)
class TrayBadgeState:
    unread_count: int = 0
    update_available: bool = False

    @property
    def visible(self) -> bool:
        return self.unread_count > 0 or self.update_available

    @property
    def text(self) -> str:
        if self.unread_count > 99:
            return "99+"
        if self.unread_count > 0:
            return str(self.unread_count)
        return "!" if self.update_available else ""
