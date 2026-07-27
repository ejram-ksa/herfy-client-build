from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require(path: str, *needles: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise SystemExit(f"{path} missing {missing}")


def reject(path: str, *needles: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    found = [needle for needle in needles if needle in text]
    if found:
        raise SystemExit(f"{path} contains forbidden {found}")


def main() -> int:
    require(
        "runtime/application/services/tracking_runtime.py",
        "class TrackingBaselineCoordinator",
        "_source_priority",
        "tracking_baseline = TrackingBaselineCoordinator()",
    )
    require(
        "runtime/presentation/views/tracking_sections/tracking_page.py",
        "_pending_tracking_delta",
        "tracking_baseline.snapshot()",
        'tracking_baseline.publish(preloaded, source="app_state")',
    )
    require(
        "runtime/application/services/tracking/service.py",
        "snapshot = tracking_baseline.snapshot()",
        "snapshot = tracking_baseline.publish(",
    )
    require(
        "runtime/presentation/main_window/monitoring.py",
        "combined: dict[str, dict]",
        "tracking_store.snapshot()",
        "records = tuple(getattr(snapshot, 'records', ()) or ())",
    )
    reject(
        "runtime/presentation/main_window/monitoring.py",
        "self.track_page.load_tracked_products(preloaded=prods",
    )
    require(
        "runtime/presentation/dialogs/notification_queue.py",
        "shown = self._show_tray_message(title, message, duration_s)",
        "if not shown and callable(self._show_card_notification)",
    )
    require(
        "runtime/presentation/dialogs/desktop_notifier.py",
        "tray.messageClicked.connect",
        "reveal_window(self._main_window)",
    )
    require(
        "runtime/application/services/notifications.py",
        "def alert_key(event: dict)",
        "material = str(data.get('material_number') or product_fallback).strip()",
    )
    require(
        "runtime/presentation/main_window/session_sections/session.py",
        "tracking_baseline.reset()",
    )
    print("HERFY_TRACKING_MONITORING_WINDOWS_NOTIFICATIONS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
