

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .main_window import HerfyMainWindow, MainWindow
    from .usage import (
        UsageController,
        UsageControllerMixin,
        UsagePrintContext,
        UsagePrintService,
    )
    from .views import (
        AdminDashboardDialog,
        HomeDashboardPage,
        HomePage,
        LoginPage,
        SettingsDialog,
        SettingsPage,
        TrackingPage,
        UsagePage,
    )
__all__ = [
    "AdminDashboardDialog",
    "HerfyMainWindow",
    "HomeDashboardPage",
    "HomePage",
    "LoginPage",
    "MainWindow",
    "SettingsDialog",
    "SettingsPage",
    "TrackingPage",
    "UsageController",
    "UsageControllerMixin",
    "UsagePage",
    "UsagePrintContext",
    "UsagePrintService",
]
_MAIN_WINDOW_EXPORTS = {"HerfyMainWindow", "MainWindow"}
_USAGE_EXPORTS = {
    "UsageController",
    "UsageControllerMixin",
    "UsagePrintContext",
    "UsagePrintService",
}
_VIEW_EXPORTS = {
    "AdminDashboardDialog",
    "HomeDashboardPage",
    "HomePage",
    "LoginPage",
    "SettingsDialog",
    "SettingsPage",
    "TrackingPage",
    "UsagePage",
}


def __getattr__(name: str):
    if name in _MAIN_WINDOW_EXPORTS:
        from . import main_window

        return getattr(main_window, name)
    if name in _USAGE_EXPORTS:
        from . import usage

        return getattr(usage, name)
    if name in _VIEW_EXPORTS:
        from . import views

        return getattr(views, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
