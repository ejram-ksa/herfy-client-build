from __future__ import annotations
from runtime.shared.booleans import parse_bool
import logging
from typing import Any
from runtime.shared.settings.config import _
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.presentation.layout.helpers import set_badge_size

logger = logging.getLogger(__name__)


class NotificationBadgeUpdater:

    def __init__(self, main_window: Any) -> None:
        self.main_window = main_window

    def update(self) -> None:
        mw = self.main_window
        try:
            unread_count = sum(
                (
                    1
                    for item in mw.notifications_list or []
                    if not parse_bool((item or {}).get("read"), False)
                )
            )
            mw.unread_notifications = int(unread_count)
            badge_text = "99+" if unread_count > 99 else str(unread_count)
            mw.lbl_notif_count.setText(badge_text)
            try:
                metrics = mw.fontMetrics()
                width = max(
                    int(mw.S(18)), metrics.horizontalAdvance(badge_text) + int(mw.S(10))
                )
                set_badge_size(mw.lbl_notif_count, width, int(mw.S(18)))
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug("Failed to resize notifications badge", exc_info=True)
            mw.btn_notifications.setToolTip(
                _("Notifications") + (f" ({unread_count})" if unread_count else "")
            )
            if unread_count > 0:
                mw.lbl_notif_count.show()
            else:
                mw.lbl_notif_count.hide()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Failed to update notifications badge", exc_info=True)
