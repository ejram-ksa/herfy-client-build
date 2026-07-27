from __future__ import annotations
import logging
from runtime.bootstrap.qt.runtime import qt_settings_class
from runtime.shared.settings.config import settings_ini_path
from runtime.shared.errors import STATE_OPERATION_EXCEPTIONS
from runtime.application.services.installer_defaults import load_installer_defaults

logger = logging.getLogger(__name__)


def apply_installer_defaults_to_qsettings() -> dict[str, str]:
    defaults = load_installer_defaults()
    if not defaults:
        return {}
    applied: dict[str, str] = {}
    try:
        QSettings = qt_settings_class()
        store = QSettings(settings_ini_path(), QSettings.IniFormat)
        for key, value in defaults.items():
            existing = store.value(key, "")
            if existing not in (None, ""):
                continue
            store.setValue(key, value)
            applied[key] = value
        store.sync()
    except STATE_OPERATION_EXCEPTIONS:
        logger.debug("Applying installer defaults to QSettings failed", exc_info=True)
    return applied
