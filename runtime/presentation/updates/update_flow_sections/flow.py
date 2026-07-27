from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

import logging
from functools import partialmethod
from PyQt5.QtWidgets import QMessageBox
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.objects import noop, normalize_int, normalized_result_key
from runtime.presentation.dialogs.update_dialogs import UpdateActionDialog, UpdateProgressDialog

logger = logging.getLogger(__name__)


def update_action_dialog_class():
    try:
        return UpdateActionDialog
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.warning("Falling back to non-interactive update action dialog")

        class _FallbackUpdateActionDialog:
            result_key = normalized_result_key

            def __init__(self, *args, **kwargs):
                self._result = "secondary"

            exec_ = staticmethod(noop)

        return _FallbackUpdateActionDialog


def update_progress_dialog_class():
    try:
        return UpdateProgressDialog
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.warning("Falling back to non-interactive update progress dialog")

        class _FallbackSignal:
            connect = staticmethod(noop)

        class _FallbackUpdateProgressDialog:

            def __init__(self, *args, **kwargs):
                self._value = 0
                self.label_text = ""
                self.detail_text = ""
                self.destroyed = _FallbackSignal()

            show = staticmethod(noop)
            hide = staticmethod(noop)

            def _set_progress_text(self, attribute: str, text: str) -> None:
                setattr(self, attribute, str(text or ""))

            setLabelText = partialmethod(_set_progress_text, "label_text")
            setDetailText = partialmethod(_set_progress_text, "detail_text")

            def setValue(self, value: int) -> None:
                self._value = int(value or 0)

            def value(self) -> int:
                return self._value

        return _FallbackUpdateProgressDialog


def prompt_update_action(
    parent,
    *,
    title: str,
    details: str,
    informative_text: str,
    icon,
    primary_text: str,
    secondary_text: str,
    tertiary_text: str | None = None,
    tertiary_role=None,
    current_version: str = "",
    target_version: str = "",
    mandatory: bool = False,
    mode: str = "update",
) -> str:
    dialog = update_action_dialog_class()(
        parent,
        title=title,
        details=details,
        informative_text=informative_text,
        primary_text=primary_text,
        secondary_text=secondary_text,
        tertiary_text=tertiary_text if tertiary_role is not None else None,
        current_version=current_version,
        target_version=target_version,
        mandatory=mandatory,
        mode=mode,
    )
    dialog.exec_()
    return dialog.result_key()


def prompt_patch_update_action(
    parent,
    info,
    *,
    title: str,
    details: str,
    informative_text: str,
    primary_text: str,
    secondary_text: str,
    icon=QMessageBox.Information,
) -> str:
    return prompt_update_action(
        parent,
        title=title,
        details=details,
        informative_text=informative_text,
        icon=icon,
        primary_text=primary_text,
        secondary_text=secondary_text,
        current_version=str(getattr(info, "current_version", "")),
        target_version=str(getattr(info, "target_version", "")),
        mandatory=bool(getattr(info, "mandatory", False)),
        mode="update",
    )


def prompt_installer_update_action(
    parent,
    info,
    *,
    title: str,
    details: str,
    informative_text: str,
    primary_text: str,
    secondary_text: str,
    tertiary_text: str,
    icon=QMessageBox.Information,
    mandatory: bool = False,
) -> str:
    action = prompt_update_action(
        parent,
        title=title,
        details=details,
        informative_text=informative_text,
        icon=icon,
        primary_text=primary_text,
        secondary_text=secondary_text,
        tertiary_text=None if mandatory else tertiary_text,
        tertiary_role=None if mandatory else QMessageBox.DestructiveRole,
        current_version=str(getattr(info, "current_version", "")),
        target_version=str(getattr(info, "latest", ""))
        or str(getattr(info, "target_version", "")),
        mandatory=mandatory,
        mode="update",
    )
    if mandatory:
        return "primary" if action == "primary" else "secondary"
    return action


from PyQt5.QtWidgets import QApplication
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS



def _widget_is_alive(widget) -> bool:
    if widget is None:
        return True
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Widget liveness check failed", exc_info=True)
        return False


def quit_application() -> None:
    app = QApplication.instance() if QApplication is not None else None
    if app is not None:
        try:
            for widget in list(app.topLevelWidgets()):
                close_completely = getattr(widget, "close_app_completely", None)
                if callable(close_completely):
                    close_completely()
                    return
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "Application shutdown via top-level window failed", exc_info=True
            )
        try:
            app.processEvents()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "Application event flush before shutdown failed", exc_info=True
            )
        app.quit()
        return
    raise SystemExit()


def invoke_parent_message(parent, method_name: str, title: str, message: str) -> bool:
    callback = getattr(parent, method_name, None)
    if not callable(callback):
        return False
    try:
        callback(title, message)
        return True
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("Parent message handler failed: %s", method_name, exc_info=True)
        return False


def _dispatch_feedback_message(
    parent, method_name: str, title: str, message: str, *, level: str
) -> None:
    if invoke_parent_message(parent, method_name, title, message):
        return
    try:
        from runtime.presentation.widgets import (
            show_error_message,
            show_info_message,
            show_question_message,
            show_warning_message,
        )
    except SERVICE_OPERATION_EXCEPTIONS:
        log_method = logger.warning if level == "warning" else logger.info
        log_method("%s: %s", title, message)
        return
    if level == "warning":
        show_warning_message(parent, title, message)
    elif level == "error":
        show_error_message(parent, title, message)
    elif level == "question":
        show_question_message(parent, title, message)
    else:
        show_info_message(parent, title, message)


def show_update_info_message(parent, title: str, message: str) -> None:
    _dispatch_feedback_message(
        parent, "_show_info_message", title, message, level="info"
    )


def show_update_warning_message(parent, title: str, message: str) -> None:
    _dispatch_feedback_message(
        parent, "_show_warning_message", title, message, level="warning"
    )


from pathlib import Path
from typing import Any
from runtime.shared.settings.config import _, runtime_cache_path
from runtime.shared.files import read_json_dict, write_json_dict
from runtime.shared.settings.messages import canonical_error_message, user_error_message
from runtime.application.services.sync import _safe_unlink
from runtime.application.services.updates import UpdateInfo, UpdateManager
from runtime.application.services.updates import PatchUpdateInfo, PatchUpdateService
from runtime.bootstrap.qt.workers import WorkerRegistry, client_thread_pool



class OnlineUpdateLifecycleMixin:

    def __init__(self, current_version: str):
        self.patch_service = PatchUpdateService(current_version)
        self.skip_file = Path(runtime_cache_path("updates/skip_version.json"))
        self.skip_file.parent.mkdir(parents=True, exist_ok=True)
        self._pool = client_thread_pool()
        self._worker_registry = WorkerRegistry(self._pool)

    def close(self) -> None:
        registry = getattr(self, "_worker_registry", None)
        if registry is not None:
            close = getattr(registry, "close", None)
            if callable(close):
                close()
            else:
                registry.cancel_all()

    def _ensure_patch_install_runtime(self, parent) -> bool:
        try:
            self.patch_service.validate_install_runtime()
            return True
        except RuntimeError:
            show_update_warning_message(
                parent,
                _("Update cannot be installed from this launch mode"),
                canonical_error_message("update_install_failed"),
            )
            return False

    def _load_skipped_version(self) -> str:
        return str(read_json_dict(self.skip_file).get("skip_version") or "")

    def _save_skipped_version(self, version: str) -> None:
        write_json_dict(self.skip_file, {"skip_version": version})

    def _clear_skipped_version(self) -> None:
        _safe_unlink(self.skip_file, log_message="Failed to clear skipped version")


class OnlineUpdatePopupMixin:

    def _show_optional_popup(self, parent, info: PatchUpdateInfo) -> str:
        action = prompt_installer_update_action(
            parent,
            info,
            title=info.popup_title or _("New update available"),
            details=info.popup_message
            or info.notes
            or _("Version {version} is available.").format(version=info.target_version),
            informative_text=_("Do you want to download and apply the update now?"),
            primary_text=_("Update now"),
            secondary_text=_("Later"),
            tertiary_text=_("Skip this version"),
        )
        if action == "primary":
            return "update"
        if action == "tertiary":
            return "skip"
        return "later"

    def _show_mandatory_popup(self, parent, info: PatchUpdateInfo) -> str:
        action = prompt_installer_update_action(
            parent,
            info,
            title=info.popup_title or _("Mandatory update required"),
            details=info.popup_message
            or info.notes
            or _("Version {version} is required to continue.").format(
                version=info.target_version
            ),
            informative_text=_(
                "You must apply this update to continue using the application."
            ),
            primary_text=_("Update now"),
            secondary_text=_("Exit application"),
            tertiary_text=_("Skip this version"),
            icon=QMessageBox.Warning,
            mandatory=True,
        )
        return "update" if action == "primary" else "exit"

    def show_no_update_popup(self, parent, current_version: str) -> None:
        show_update_info_message(
            parent,
            _("Updates"),
            _("You are already on the latest version ({version}).").format(
                version=current_version
            ),
        )


class OnlineUpdateProgressMixin:

    def _create_progress_dialog(self, parent, info: PatchUpdateInfo) -> Any:
        return update_progress_dialog_class()(
            parent,
            title=_("Updating application"),
            label_text=_("Downloading update {version}...").format(
                version=info.target_version
            ),
        )

    def _progress_label_text(
        self,
        info: PatchUpdateInfo,
        percent: int = 0,
        downloaded: int = 0,
        total: int = 0,
    ) -> str:
        return _("Downloading update {version}...").format(version=info.target_version)

    @staticmethod
    def _download_detail_text(downloaded: int, total: int) -> str:
        if total > 0:
            return _("{downloaded} KB / {total} KB").format(
                downloaded=downloaded // 1024, total=total // 1024
            )
        return _("{downloaded} KB downloaded").format(downloaded=downloaded // 1024)

    def _apply_download_progress(self, dialog, label_text: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        percent = max(0, min(100, normalize_int(payload.get("percent"), 0)))
        downloaded = max(0, normalize_int(payload.get("downloaded"), 0))
        total = max(0, normalize_int(payload.get("total"), 0))
        raw_stage = str(payload.get("stage") or "download").strip().lower()
        if percent >= 100:
            stage = _("Verifying downloaded package")
        elif downloaded <= 0:
            stage = _("Connecting to update server")
        elif "verify" in raw_stage or "checksum" in raw_stage:
            stage = _("Verifying downloaded package")
        else:
            stage = _("Downloading update package")
        dialog.setLabelText(label_text)
        if hasattr(dialog, "setStageText"):
            dialog.setStageText(stage)
        if hasattr(dialog, "setFooterText"):
            dialog.setFooterText(
                _(
                    "The update will install automatically and Herfy Client will open again."
                )
            )
        dialog.setDetailText(self._download_detail_text(downloaded, total))
        dialog.setValue(max(0, min(100, percent)))

    @staticmethod
    def _apply_installing_state(dialog, label_text: str, detail_text: str) -> None:
        dialog.setLabelText(label_text)
        if hasattr(dialog, "setStageText"):
            dialog.setStageText("Installing")
        if hasattr(dialog, "setFooterText"):
            dialog.setFooterText(
                _(
                    "Do not close this window. The application will restart automatically."
                )
            )
        dialog.setDetailText(detail_text)
        dialog.setValue(100)

    def _show_download_error(self, parent, message: str) -> None:
        show_update_warning_message(
            parent, _("Update failed"), user_error_message(message, context="update")
        )

    def _handle_worker_download_error(self, dialog, parent, message: str) -> None:
        if _widget_is_alive(dialog):
            dialog.hide()
        if _widget_is_alive(parent):
            self._show_download_error(parent, message)


class OnlineUpdateDownloadMixin:

    def _start_download_worker(
        self, dialog, parent, work, on_progress, on_result
    ) -> None:
        self._worker_registry.start(
            work,
            on_progress=on_progress,
            on_result=on_result,
            on_error=lambda msg: self._handle_worker_download_error(
                dialog, parent, msg
            ),
            on_finished=lambda: (
                dialog.hide()
                if _widget_is_alive(dialog) and dialog.value() < 100
                else None
            ),
            operation_key="update:download",
            scope_checker=lambda: _widget_is_alive(dialog) and _widget_is_alive(parent),
            log_exceptions=False,
        )

    def download_installer_and_run(self, parent, info: UpdateInfo) -> None:
        dialog = update_progress_dialog_class()(
            parent,
            title=_("Updating application"),
            label_text=_("Downloading installer {version}...").format(
                version=info.latest
            ),
        )
        dialog.destroyed.connect(lambda *_args: self.close())
        dialog.show()
        manager = UpdateManager(self.patch_service.current_version)

        def download_task(progress_callback=None):
            return str(
                manager.download_installer(info, progress_callback=progress_callback)
            )

        def _on_progress(payload):
            self._apply_download_progress(
                dialog,
                _("Downloading installer {version}...").format(version=info.latest),
                payload,
            )

        def _on_result(installer_path: str):
            self._apply_installing_state(
                dialog,
                _("Installing update..."),
                _(
                    "The installer progress window will open now. The application will close automatically."
                ),
            )
            try:
                if not UpdateManager._launch_installer_silent(Path(installer_path)):
                    raise RuntimeError(_("Downloaded installer could not be started"))
            except UI_OPERATION_EXCEPTIONS as exc:
                self._handle_worker_download_error(dialog, parent, str(exc))
                return
            quit_application()

        self._start_download_worker(
            dialog, parent, download_task, _on_progress, _on_result
        )

    def download_and_apply(self, parent, info: PatchUpdateInfo) -> None:
        if not self._ensure_patch_install_runtime(parent):
            return
        dialog = self._create_progress_dialog(parent, info)
        dialog.destroyed.connect(lambda *_args: self.close())
        dialog.show()

        def download_task(progress_callback=None):
            return str(
                self.patch_service.download_patch(
                    info, progress_callback=progress_callback
                )
            )

        def _on_progress(payload):
            self._apply_download_progress(
                dialog, self._progress_label_text(info), payload
            )

        def _on_result(patch_path: str):
            self._apply_installing_state(
                dialog,
                _("Installing update..."),
                _("Replacing application files and restarting..."),
            )
            self._clear_skipped_version()
            try:
                self.patch_service.launch_update_agent(Path(patch_path), info)
            except UI_OPERATION_EXCEPTIONS as exc:
                self._handle_worker_download_error(dialog, parent, str(exc))
                return
            quit_application()

        self._start_download_worker(
            dialog, parent, download_task, _on_progress, _on_result
        )


class OnlineUpdateCheckMixin:

    def check_and_prompt_async(self, parent) -> None:
        skipped_version = self._load_skipped_version()

        def _work(progress_callback=None):
            patch_info = self.patch_service.fetch()
            installer_info = None
            if not (
                patch_info.available
                and (patch_info.package_name or patch_info.download_url)
                and (
                    not (
                        not patch_info.mandatory
                        and skipped_version == patch_info.target_version
                    )
                )
            ):
                installer_info = UpdateManager(
                    self.patch_service.current_version
                ).fetch(skipped_version=skipped_version)
            return {
                "skipped_version": skipped_version,
                "patch": patch_info,
                "installer": installer_info,
            }

        def _on_result(payload):
            if _widget_is_alive(parent):
                self._handle_check_payload(parent, payload or {})

        self._worker_registry.start(
            _work,
            on_result=_on_result,
            on_error=lambda msg: logger.warning("Online update check skipped: %s", msg),
            operation_key="update:check",
            scope_checker=lambda: _widget_is_alive(parent),
            log_exceptions=False,
        )

    def _handle_check_payload(self, parent, payload: dict) -> None:
        skipped_version = str(payload.get("skipped_version") or "")
        info = payload.get("patch")
        installer_for_badge = payload.get("installer")
        patch_available_for_badge = bool(
            info is not None
            and getattr(info, "available", False)
            and (getattr(info, "package_name", "") or getattr(info, "download_url", ""))
        )
        installer_available_for_badge = bool(
            installer_for_badge is not None
            and getattr(installer_for_badge, "available", False)
            and getattr(installer_for_badge, "url", "")
        )
        badge_setter = getattr(parent, "set_tray_update_available", None)
        if callable(badge_setter):
            badge_setter(patch_available_for_badge or installer_available_for_badge)
        if (
            info is not None
            and info.available
            and (info.package_name or info.download_url)
            and (not (not info.mandatory and skipped_version == info.target_version))
        ):
            action = (
                self._show_mandatory_popup(parent, info)
                if info.mandatory
                else self._show_optional_popup(parent, info)
            )
            if action == "skip" and (not info.mandatory):
                self._save_skipped_version(info.target_version)
                return
            if action in {"later", "exit"}:
                if action == "exit" and info.mandatory:
                    quit_application()
                return
            self.download_and_apply(parent, info)
            return
        installer = payload.get("installer")
        if installer is None:
            logger.debug(
                "Online update payload did not include installer information; skipped synchronous fallback"
            )
            return
        if not installer.available or not installer.url:
            return
        action = prompt_installer_update_action(
            parent,
            installer,
            title=(
                _("Mandatory update required")
                if installer.mandatory
                else _("Update available")
            ),
            details=installer.notes
            or _("Version {version} is available.").format(version=installer.latest),
            informative_text=(
                _("You must install this update to continue.")
                if installer.mandatory
                else _("Do you want to download and run the installer now?")
            ),
            primary_text=_("Update now"),
            secondary_text=_("Exit application") if installer.mandatory else _("Later"),
            tertiary_text=_("Skip this version"),
            icon=(
                QMessageBox.Warning if installer.mandatory else QMessageBox.Information
            ),
            mandatory=bool(installer.mandatory),
        )
        if action == "tertiary" and (not installer.mandatory):
            self._save_skipped_version(installer.latest)
            return
        if action in {"secondary", "later", "exit"}:
            if installer.mandatory:
                quit_application()
            return
        self.download_installer_and_run(parent, installer)

    def check_and_prompt(self, parent) -> None:
        skipped_version = self._load_skipped_version()
        info = self.patch_service.fetch()
        badge_setter = getattr(parent, "set_tray_update_available", None)
        patch_available_for_badge = bool(
            info.available and (info.package_name or info.download_url)
        )
        if callable(badge_setter):
            badge_setter(patch_available_for_badge)
        if (
            info.available
            and (info.package_name or info.download_url)
            and (not (not info.mandatory and skipped_version == info.target_version))
        ):
            action = (
                self._show_mandatory_popup(parent, info)
                if info.mandatory
                else self._show_optional_popup(parent, info)
            )
            if action == "skip" and (not info.mandatory):
                self._save_skipped_version(info.target_version)
                return
            if action in {"later", "exit"}:
                if action == "exit" and info.mandatory:
                    quit_application()
                return
            self.download_and_apply(parent, info)
            return
        installer = UpdateManager(self.patch_service.current_version).fetch(
            skipped_version=skipped_version
        )
        if callable(badge_setter):
            badge_setter(bool(installer.available and installer.url))
        if not installer.available or not installer.url:
            return
        action = prompt_installer_update_action(
            parent,
            installer,
            title=(
                _("Mandatory update required")
                if installer.mandatory
                else _("Update available")
            ),
            details=installer.notes
            or _("Version {version} is available.").format(version=installer.latest),
            informative_text=(
                _("You must install this update to continue.")
                if installer.mandatory
                else _("Do you want to download and run the installer now?")
            ),
            primary_text=_("Update now"),
            secondary_text=_("Exit application") if installer.mandatory else _("Later"),
            tertiary_text=_("Skip this version"),
            icon=(
                QMessageBox.Warning if installer.mandatory else QMessageBox.Information
            ),
            mandatory=bool(installer.mandatory),
        )
        if action == "tertiary" and (not installer.mandatory):
            self._save_skipped_version(installer.latest)
            return
        if action in {"secondary", "later", "exit"}:
            if installer.mandatory:
                quit_application()
            return
        self.download_installer_and_run(parent, installer)
