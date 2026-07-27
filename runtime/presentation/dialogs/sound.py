from __future__ import annotations
import importlib
import logging
import os
from collections.abc import Callable
from typing import Any
from PyQt5.QtCore import QUrl
from runtime.shared.settings.config import (
    IS_WINDOWS,
    NOTIFICATION_SOUND_DIR_RELATIVE_PATH,
    resource_path,
)
from runtime.shared.booleans import setting_bool
from runtime.shared.errors import (
    IMPORT_OPERATION_EXCEPTIONS,
    SERVICE_OPERATION_EXCEPTIONS,
    UI_OPERATION_EXCEPTIONS,
)
from runtime.application.services.notifications import NotificationEngine

try:
    _qt_multimedia = importlib.import_module("PyQt5.QtMultimedia")
    QMediaContent = _qt_multimedia.QMediaContent
    QMediaPlayer = _qt_multimedia.QMediaPlayer
except IMPORT_OPERATION_EXCEPTIONS:
    QMediaContent = None
    QMediaPlayer = None
logger = logging.getLogger(__name__)


class SoundNotifier:

    def __init__(self, get_setting: Callable[[str, Any], Any]) -> None:
        self._get_setting = get_setting
        self._player = None
        if QMediaPlayer:
            try:
                self._player = QMediaPlayer()
            except SERVICE_OPERATION_EXCEPTIONS:
                self._player = None

    @staticmethod
    def setting_key_for_status(status: str | dict) -> str:
        """Return the configured sound key using canonical notification status.

        The sound route must not depend only on translated labels.  It first
        uses NotificationEngine status_kind/severity data, then falls back to
        the public text parser inside the service.
        """
        try:
            return NotificationEngine.sound_setting_key(status)
        except SERVICE_OPERATION_EXCEPTIONS:
            text = str(status or "").strip().lower()
            if any(
                (
                    token in text
                    for token in ("expired", "overdue", "انتهى", "منتهي", "مضى")
                )
            ):
                return "notification_sound_expired"
            if any((token in text for token in ("today", "اليوم"))):
                return "notification_sound_today"
            if any(
                (
                    token in text
                    for token in ("critical", "expires after", "خطر", "ينتهي بعد")
                )
            ):
                return "notification_sound_critical"
            if any(
                (
                    token in text
                    for token in ("soon", "warning", "expiring", "قريب", "تحذير")
                )
            ):
                return "notification_sound_soon"
            return "notification_sound_default"

    def resolve_sound_path(self, status: str = "") -> str:
        key = self.setting_key_for_status(status)
        selected = str(self._get_setting(key, "") or "").strip()
        if not selected:
            selected = str(
                self._get_setting("notification_sound_default", "default.wav")
                or "default.wav"
            ).strip()
        sound_path = resource_path(
            *NOTIFICATION_SOUND_DIR_RELATIVE_PATH, selected or "default.wav"
        )
        if os.path.exists(sound_path):
            return sound_path
        fallback = resource_path(*NOTIFICATION_SOUND_DIR_RELATIVE_PATH, "default.wav")
        return fallback if os.path.exists(fallback) else ""

    def play(self, status: str = "") -> None:
        if not setting_bool(self._get_setting, "enable_sounds", True):
            return
        sound_path = self.resolve_sound_path(status)
        if not sound_path:
            return
        if self._play_qt(sound_path):
            return
        try:
            if IS_WINDOWS:
                winsound = importlib.import_module("winsound")
                if sound_path.lower().endswith(".wav"):
                    winsound.PlaySound(
                        sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC
                    )
                else:
                    winsound.MessageBeep()
            else:
                logger.warning(
                    "Notification sound backend unavailable for: %s", sound_path
                )
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            logger.error("Sound error: %s", exc)

    def play_file_via_qt(self, sound_path: str) -> bool:
        return self._play_qt(sound_path)

    def _play_qt(self, sound_path: str) -> bool:
        if not sound_path or not (self._player and QMediaContent and QUrl):
            return False
        try:
            self._player.stop()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Media player stop failed before replay", exc_info=True)
        try:
            self._player.setMedia(QMediaContent(QUrl.fromLocalFile(sound_path)))
            self._player.play()
            return True
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception("Qt sound playback failed")
            return False

    def stop(self) -> None:
        try:
            player = getattr(self, "_player", None)
            if player is not None:
                player.stop()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Sound notifier shutdown failed", exc_info=True)
