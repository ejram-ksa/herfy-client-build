from __future__ import annotations

from runtime.shared.objects import normalize_int
from .sound import SoundNotifier
from .notification_state import NotificationDuplicateGuard, NotificationHistoryStore
from .notification_queue import DesktopNotificationQueue
from .notification_badge import NotificationBadgeUpdater
from .desktop_notifier import DesktopNotifier
import logging
from runtime.shared.settings.config import _
from runtime.shared.booleans import setting_bool
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.application.services.notifications import (
    NotificationDecisionService,
    NotificationEngine,
)

logger = logging.getLogger(__name__)


class NotificationService:

    def __init__(self, main_window):
        self.main_window = main_window
        self.desktop_notifier = DesktopNotifier(main_window)
        self.sound_notifier = SoundNotifier(self._get_setting)
        self.engine = NotificationEngine()
        self.decision_service = NotificationDecisionService(self.engine)
        self.duplicate_guard = NotificationDuplicateGuard()
        self.badge_updater = NotificationBadgeUpdater(main_window)
        self.history_store = NotificationHistoryStore(
            main_window, self.engine, max_items=500
        )
        self.desktop_queue = DesktopNotificationQueue(
            main_window,
            get_bool=self._get_bool,
            show_tray_message=self.desktop_notifier.show_tray_message,
            show_card_notification=self.desktop_notifier.show_card_notification,
            play_sound=self.sound_notifier.play,
        )

    def _get_setting(self, key: str, default=None):
        try:
            return self.main_window.db_manager.get_setting(key, default)
        except SERVICE_OPERATION_EXCEPTIONS:
            return default

    def _get_bool(self, key: str, default: bool = False) -> bool:
        try:
            return setting_bool(self._get_setting, key, default)
        except SERVICE_OPERATION_EXCEPTIONS:
            return bool(default)

    def _get_int(self, key: str, default: int) -> int:
        try:
            return int(self._get_setting(key, str(default)))
        except SERVICE_OPERATION_EXCEPTIONS:
            return default

    def _enqueue_desktop_notification(
        self,
        *,
        title: str,
        message: str,
        duration_s: int,
        status: str = "",
        entry: dict | None = None,
    ) -> None:
        self.desktop_queue.enqueue(
            title=title,
            message=message,
            duration_s=duration_s,
            status=status,
            entry=entry,
        )

    def _dispatch_popup(
        self,
        title: str,
        short_msg: str,
        full_msg: str,
        status: str,
        dedupe_key: str,
        entry: dict | None = None,
    ):
        dur_s = min(30, max(3, self._get_int("notification_duration_seconds", 8)))
        if not self.duplicate_guard.mark_recent(
            f"popup|{dedupe_key}", ttl_seconds=10.0
        ):
            return
        message = str(full_msg or short_msg or "").strip()
        self._enqueue_desktop_notification(
            title=title, message=message, duration_s=dur_s, status=status, entry=entry
        )

    def _record_history_entries(self, entries: list[dict]) -> None:
        if not entries:
            return
        changed = self.history_store.record_entries(list(entries or []))
        if changed:
            self.badge_updater.update()

    def _evaluate_event(self, event: dict) -> tuple[bool, dict]:
        decision_service = getattr(self, "decision_service", None)
        if decision_service is None:
            decision_service = NotificationDecisionService(self.engine)
            self.decision_service = decision_service
        decision = decision_service.evaluate(
            self.main_window.db_manager,
            event,
            repeat_minutes=self._get_int(
                "notification_repeat_interval_minutes", 240
            ),
            once_per_day=self._get_bool("notification_once_per_day", True),
        )
        return decision.should_notify, decision.details()

    def publish_alerts(self, alerts: list[dict]) -> None:
        if not alerts:
            return
        notify_candidates: list[dict] = []
        history_entries: list[dict] = []
        for event in alerts:
            if not isinstance(event, dict):
                continue
            if not self.engine.is_notifiable_source(event):
                continue
            if not self.engine.is_notifiable_status(event):
                continue
            key = self.engine.alert_key(event)
            if not key:
                continue
            should_notify, _reason = self._evaluate_event(event)
            if should_notify:
                notify_candidates.append(event)
                history_entries.append(self.engine.history_entry(event))
        self._record_history_entries(history_entries)
        if not notify_candidates:
            return
        notify_candidates.sort(key=self.engine.sort_key, reverse=True)
        smart_enabled = self._get_bool("enable_smart_notifications", True)
        summary_threshold = min(
            50, max(2, self._get_int("notification_summary_threshold", 3))
        )
        max_per_cycle = min(20, max(1, self._get_int("notification_max_per_cycle", 5)))
        branches = {
            str(event.get("branch") or "").strip().lower()
            for event in notify_candidates
            if str(event.get("branch") or "").strip()
        }
        if smart_enabled and (
            len(notify_candidates) >= summary_threshold or len(branches) > 1
        ):
            self._dispatch_summary(notify_candidates)
            return
        urgent_events = [
            event
            for event in notify_candidates
            if not self.engine.is_summary_preferred(event)
        ]
        soon_events = [
            event
            for event in notify_candidates
            if self.engine.is_summary_preferred(event)
        ]
        dispatched = 0
        for event in urgent_events[:max_per_cycle]:
            self._dispatch_detail(event)
            dispatched += 1
        remaining_urgent = urgent_events[max_per_cycle:]
        if remaining_urgent:
            self._dispatch_summary(
                remaining_urgent,
                prefix_count=len(remaining_urgent),
                title_override=_("More urgent alerts"),
            )
            return
        remaining_slots = max(0, max_per_cycle - dispatched)
        if not soon_events or remaining_slots <= 0:
            return
        if smart_enabled and len(soon_events) >= summary_threshold:
            self._dispatch_summary(soon_events)
            return
        for event in soon_events[:remaining_slots]:
            self._dispatch_detail(event)
            dispatched += 1
        remaining_soon = soon_events[remaining_slots:]
        if remaining_soon:
            self._dispatch_summary(
                remaining_soon,
                prefix_count=len(remaining_soon),
                title_override=_("More alerts"),
            )

    def _dispatch_detail(self, event: dict) -> None:
        title = _("Products expiration tracking")
        short_msg = f"{event.get('product_name') or event.get('display_product') or ''} - {event.get('status') or ''}".strip(
            " -"
        )
        self._dispatch_popup(
            title,
            short_msg,
            str(event.get("message") or short_msg),
            str(event.get("status") or ""),
            self.engine.alert_key(event),
            entry=self.engine.history_entry(event),
        )

    def _dispatch_summary(
        self,
        events: list[dict],
        *,
        prefix_count: int | None = None,
        title_override: str | None = None,
    ) -> None:
        if not events:
            return
        critical = sum(
            (1 for ev in events if normalize_int(ev.get("severity_rank"), 0) >= 4)
        )
        warning = sum(
            (1 for ev in events if normalize_int(ev.get("severity_rank"), 0) == 3)
        )
        expired = sum(
            (1 for ev in events if "expired" in str(ev.get("status") or "").lower())
        )
        total = int(prefix_count or len(events))
        title = str(title_override or _("Products expiration tracking"))
        parts = [
            (
                f"{total} {_('food items need attention')}"
                if total != 1
                else f"1 {_('food item needs attention')}"
            )
        ]
        if expired:
            parts.append(f"{_('Expired')}: {expired}")
        if critical:
            parts.append(f"{_('Critical')}: {critical}")
        if warning:
            parts.append(f"{_('Expiring Soon')}: {warning}")
        lead_names = [
            str(ev.get("display_product") or ev.get("product_name") or "").strip()
            for ev in events[:3]
            if str(ev.get("display_product") or ev.get("product_name") or "").strip()
        ]
        summary = " | ".join(parts)
        branches = [
            str(ev.get("branch") or "").strip()
            for ev in events
            if str(ev.get("branch") or "").strip()
        ]
        if branches:
            unique_branches = list(dict.fromkeys(branches))[:6]
            stores = [
                (
                    branch
                    if branch.upper().startswith("H")
                    else f"H{branch}" if branch.isdigit() else branch
                )
                for branch in unique_branches
            ]
            summary += "\n" + f"{_('Stores')}: " + ", ".join(stores)
        if lead_names:
            summary += "\n" + ", ".join(lead_names)
        self._dispatch_popup(
            title,
            summary.split("\n", 1)[0],
            summary,
            "warning",
            f"summary|{','.join(lead_names)}|{total}",
            entry={
                "status_label": _("Summary"),
                "days_text": str(total),
                "message": summary,
            },
        )

    def build_event(
        self,
        product_name: str,
        qty: int,
        st_text: str,
        rd_: int,
        branch: str = "",
        material_number: str = "",
        production_date: str = "",
        expiry_date: str = "",
        severity: str | None = None,
        source: str = "local",
        severity_rank: int | None = None,
        store: str = "",
        store_name: str = "",
        branch_name: str = "",
        branch_label: str = "",
        region: str = "",
        area: str = "",
    ):
        return self.engine.build_event(
            product_name=product_name,
            qty=qty,
            st_text=st_text,
            rd_=rd_,
            branch=branch,
            material_number=material_number,
            production_date=production_date,
            expiry_date=expiry_date,
            severity=severity,
            source=source,
            severity_rank=severity_rank,
            store=store,
            store_name=store_name,
            branch_name=branch_name,
            branch_label=branch_label,
            region=region,
            area=area,
        )

    def reset_runtime_state(self, *, clear_history: bool = True) -> None:
        try:
            self.duplicate_guard.clear()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Failed to clear notification duplicate guard", exc_info=True)
        try:
            self.desktop_queue.clear()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Failed to clear notification desktop queue", exc_info=True)
        if clear_history:
            try:
                self.history_store.clear_runtime_items()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug("Failed to clear notification history", exc_info=True)
        self.update_badge()

    def close(self) -> None:
        """Stop all notification delivery resources owned by this service."""
        try:
            self.desktop_queue.close()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Desktop notification queue close failed", exc_info=True)
        try:
            self.desktop_notifier.close()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Desktop notifier close failed", exc_info=True)
        try:
            self.sound_notifier.stop()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Notification sound stop failed", exc_info=True)

    def update_badge(self):
        """Update badge."""
        self.badge_updater.update()
