from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .admin_page import AdminDashboardDialog
    from runtime.presentation.views.home_sections import HomeDashboardPage, HomePage
    from .login_page import LoginPage
    from .settings_page import SettingsDialog, SettingsPage
    from runtime.presentation.views.tracking_sections import TrackingPage
    from .usage_page import UsagePage
__all__ = [
    "AdminDashboardDialog",
    "HomeDashboardPage",
    "HomePage",
    "LoginPage",
    "SettingsDialog",
    "SettingsPage",
    "TrackingPage",
    "UsagePage",
]


def __getattr__(name: str):
    if name == "AdminDashboardDialog":
        from .admin_page import AdminDashboardDialog

        return AdminDashboardDialog
    if name in {"HomeDashboardPage", "HomePage"}:
        from runtime.presentation.views.home_sections import HomeDashboardPage, HomePage

        return {"HomeDashboardPage": HomeDashboardPage, "HomePage": HomePage}[name]
    if name == "LoginPage":
        from .login_page import LoginPage

        return LoginPage
    if name in {"SettingsDialog", "SettingsPage"}:
        from .settings_page import SettingsDialog, SettingsPage

        return {"SettingsDialog": SettingsDialog, "SettingsPage": SettingsPage}[name]
    if name == "TrackingPage":
        from runtime.presentation.views.tracking_sections import TrackingPage

        return TrackingPage
    if name == "UsagePage":
        from .usage_page import UsagePage

        return UsagePage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
