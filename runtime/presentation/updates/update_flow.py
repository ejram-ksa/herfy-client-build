from __future__ import annotations
from runtime.presentation.updates.update_flow_sections import (
    prompt_installer_update_action,
    prompt_patch_update_action,
    prompt_update_action,
    update_action_dialog_class,
    update_progress_dialog_class,
)
from runtime.presentation.updates.update_flow_sections import (
    _dispatch_feedback_message,
    _widget_is_alive,
    invoke_parent_message,
    quit_application,
    show_update_info_message,
    show_update_warning_message,
)
from runtime.presentation.updates.update_flow_sections import (
    OnlineUpdateCheckMixin,
    OnlineUpdateDownloadMixin,
    OnlineUpdateLifecycleMixin,
    OnlineUpdatePopupMixin,
    OnlineUpdateProgressMixin,
)


class OnlineUpdateService(
    OnlineUpdateLifecycleMixin,
    OnlineUpdatePopupMixin,
    OnlineUpdateProgressMixin,
    OnlineUpdateDownloadMixin,
    OnlineUpdateCheckMixin,
):
    pass


__all__ = [
    "OnlineUpdateService",
    "_dispatch_feedback_message",
    "_widget_is_alive",
    "invoke_parent_message",
    "prompt_installer_update_action",
    "prompt_patch_update_action",
    "prompt_update_action",
    "quit_application",
    "show_update_info_message",
    "show_update_warning_message",
    "update_action_dialog_class",
    "update_progress_dialog_class",
]
