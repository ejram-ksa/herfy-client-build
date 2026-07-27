from __future__ import annotations
from runtime.presentation.main_window.action_sections import AppLifecycleControllerMixin
from runtime.presentation.main_window.session_sections import SessionAuthControllerMixin
from runtime.presentation.main_window.session_sections import SessionRestoreControllerMixin


class MainWindowSessionMixin(
    SessionAuthControllerMixin,
    SessionRestoreControllerMixin,
    AppLifecycleControllerMixin,
):
    pass
