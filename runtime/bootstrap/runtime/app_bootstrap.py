from __future__ import annotations
from cli import handle_cli_shortcut
from runtime.shared.settings.config import prepare_runtime_environment
from runtime.shared.settings.logging_setup import setup_crash_logging
from contextlib import suppress
import logging
import sys
import threading
from typing import Any
from runtime.bootstrap.qt.runtime import qt_settings_class, qt_timer_class
from runtime.bootstrap.runtime.single_instance import (
    acquire_runtime,
    cleanup as cleanup_single_instance,
    reveal_window,
)
from runtime.shared.settings.config import (
    APP_DESKTOP_APP_ID,
    APP_DISPLAY_NAME,
    APP_ORGANIZATION_NAME,
    settings_ini_path,
)
from runtime.shared.errors import (
    SERVICE_OPERATION_EXCEPTIONS,
    STATE_OPERATION_EXCEPTIONS,
    UI_OPERATION_EXCEPTIONS,
)
from runtime.shared.settings.logging_setup import install_exception_hooks
from runtime.shared.booleans import parse_bool

from runtime.services.lifecycle import close_runtime_client

logger = logging.getLogger(__name__)


def _qt_application_class():
    from PyQt5.QtWidgets import QApplication

    return QApplication


def _qt_core_application_class():
    from PyQt5.QtCore import QCoreApplication

    return QCoreApplication


def _qt_namespace():
    from PyQt5.QtCore import Qt

    return Qt


def _show_error_box(title: str, text: str) -> None:
    try:
        QApplication = _qt_application_class()
        from runtime.presentation.widgets import show_error_message

        if QApplication.instance() is not None:
            show_error_message(None, title, text)
    except (ModuleNotFoundError, *UI_OPERATION_EXCEPTIONS):
        logger.debug("Unable to show fatal error dialog", exc_info=True)


def _configure_high_dpi() -> None:
    QCoreApplication = _qt_core_application_class()
    QApplication = _qt_application_class()
    Qt = _qt_namespace()
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy") and hasattr(
        QApplication, "setHighDpiScaleFactorRoundingPolicy"
    ):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )


def _configure_windows_identity() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_DESKTOP_APP_ID
        )
    except (AttributeError, ImportError, OSError, ValueError):
        logger.debug("Failed to set Windows AppUserModelID", exc_info=True)


def _create_application():
    QApplication = _qt_application_class()
    try:
        QApplication.setDesktopSettingsAware(True)
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Desktop settings awareness could not be enabled", exc_info=True)
    app = QApplication(sys.argv)
    install_exception_hooks(_show_error_box)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setOrganizationName(APP_ORGANIZATION_NAME)
    if hasattr(app, "setOrganizationDomain"):
        app.setOrganizationDomain("herfy.online")
    app.setQuitOnLastWindowClosed(False)
    return app


def _apply_visual_identity(app: Any) -> None:
    try:
        from runtime.presentation.theme import apply_packaged_theme
        from runtime.presentation.widgets import apply_application_icon

        apply_application_icon(app)
        apply_packaged_theme(app)
        if hasattr(app, "setApplicationDisplayName"):
            app.setApplicationDisplayName(APP_DISPLAY_NAME)
        if hasattr(app, "setDesktopFileName"):
            app.setDesktopFileName(APP_DESKTOP_APP_ID)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.exception("Failed to apply application visual identity")


def _apply_installer_defaults() -> None:
    """Apply installer-selected safe defaults before startup language is read."""
    try:
        from runtime.bootstrap.app.installer_settings import apply_installer_defaults_to_qsettings

        apply_installer_defaults_to_qsettings()
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("Applying installer defaults failed", exc_info=True)


def _apply_startup_language(app: Any) -> None:
    try:
        QSettings = qt_settings_class()
        Qt = _qt_namespace()
        store = QSettings(settings_ini_path(), QSettings.IniFormat)
        from runtime.application.services.translations import normalize_language_code

        language = normalize_language_code(str(store.value("language", "ar") or "ar"))
        app.setLayoutDirection(Qt.RightToLeft if language == "ar" else Qt.LeftToRight)
    except STATE_OPERATION_EXCEPTIONS:
        logger.exception("Failed to read startup language setting")


def _startup_setting(key: str, default: str = "True") -> bool:
    try:
        QSettings = qt_settings_class()
        store = QSettings(settings_ini_path(), QSettings.IniFormat)
        return parse_bool(store.value(key, default), parse_bool(default, True))
    except STATE_OPERATION_EXCEPTIONS:
        return parse_bool(default, True)


def _background_sync_remote_ui() -> None:
    if not _startup_setting("refresh_remote_ui_on_startup", "False"):
        return
    try:
        from runtime.application.services.sync import RemoteAssetService

        RemoteAssetService().sync_assets()
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.exception("Remote asset sync failed")


def _start_minimized(window: Any) -> None:
    try:
        window.db_manager.set_setting("enable_tray_background", "True")
    except STATE_OPERATION_EXCEPTIONS:
        logger.exception("Failed to persist tray startup preference")
    try:
        if not window._minimize_to_tray(show_message=False):
            window.hide()
    except UI_OPERATION_EXCEPTIONS:
        logger.exception("Failed to start minimized to tray")
        window.hide()
    if not _startup_setting("reveal_login_after_tray_startup", "False"):
        return

    def reveal_login_if_needed() -> None:
        try:
            if getattr(window, "session", None) is None:
                window._restore_from_tray()
        except UI_OPERATION_EXCEPTIONS:
            logger.exception("Failed to reveal login window after tray startup")

    QTimer = qt_timer_class()
    QTimer.singleShot(5000, reveal_login_if_needed)


def _ensure_background_runtime(window: Any) -> None:
    """Keep tray/background operation enabled for the single running process."""

    try:
        window.db_manager.set_setting("enable_tray_background", "True")
        refresh_tray = getattr(window, "refresh_tray_icon", None)
        if callable(refresh_tray):
            refresh_tray()
    except STATE_OPERATION_EXCEPTIONS:
        logger.exception("Failed to enable the background runtime")


def _show_startup_window(window: Any) -> None:
    """Show an ordinary launch while background services remain active."""

    try:
        window.show()
        reveal_window(window)
    except UI_OPERATION_EXCEPTIONS:
        logger.exception("Failed to reveal the startup window")
        with suppress(UI_OPERATION_EXCEPTIONS):
            window.show()


def _shutdown_cleanup(window: Any, lock: Any) -> None:
    shutdown_runtime = getattr(window, "_shutdown_runtime_resources", None)
    if callable(shutdown_runtime):
        try:
            shutdown_runtime(from_about_to_quit=True)
        except UI_OPERATION_EXCEPTIONS:
            logger.exception("Runtime cleanup during shutdown failed")
    else:
        destroy_tray = getattr(window, "_destroy_tray_icon", None)
        if callable(destroy_tray):
            try:
                destroy_tray()
            except UI_OPERATION_EXCEPTIONS:
                logger.exception("Tray cleanup during shutdown failed")
        api_client = getattr(getattr(window, "app_state", None), "api_client", None)
        try:
            close_runtime_client(api_client)
        except STATE_OPERATION_EXCEPTIONS:
            logger.exception("API client shutdown cleanup failed")
    cleanup_single_instance(window, lock)


def run_gui_application(container: Any) -> int:
    QTimer = qt_timer_class()
    from runtime.presentation.main_window.window import HerfyMainWindow

    _configure_high_dpi()
    _configure_windows_identity()
    app = _create_application()
    _apply_visual_identity(app)
    _apply_installer_defaults()
    _apply_startup_language(app)
    single_instance = acquire_runtime(sys.argv[1:])
    if not single_instance.acquired:
        return 0
    window = None
    try:
        window = HerfyMainWindow(container)
        _ensure_background_runtime(window)
        single_instance.start_server(window)
        app.aboutToQuit.connect(lambda: _shutdown_cleanup(window, single_instance.lock))
        background_flags = {"--tray", "--background"}
        start_minimized_requested = any(
            str(argument).strip().lower() in background_flags
            for argument in sys.argv[1:]
        )
        if start_minimized_requested:
            _start_minimized(window)
        else:
            _show_startup_window(window)
        QTimer.singleShot(
            0,
            lambda: threading.Thread(
                target=_background_sync_remote_ui,
                name="herfy-remote-ui-sync",
                daemon=True,
            ).start(),
        )
        return app.exec_()
    finally:
        if window is not None:
            _shutdown_cleanup(window, single_instance.lock)
        else:

            class _StartupCleanupWindow:
                __slots__ = ()

            cleanup_single_instance(_StartupCleanupWindow(), single_instance.lock)


def run(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    cli_result = handle_cli_shortcut(args)
    if cli_result is not None:
        return cli_result
    prepare_runtime_environment()
    setup_crash_logging()
    install_exception_hooks()
    from runtime.bootstrap.runtime.dependency_container import (
        configure_application_ports,
        create_dependency_container,
    )

    configure_application_ports()
    return run_gui_application(create_dependency_container())


if __name__ == "__main__":
    raise SystemExit(run())
