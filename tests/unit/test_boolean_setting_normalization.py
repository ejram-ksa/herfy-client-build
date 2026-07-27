from __future__ import annotations

from runtime.application.services.auth import LoginRemoteNoticeService
from runtime.application.services.usage.service import UsageWorkspaceService


class _Settings:
    def __init__(self, value):
        self.value = value

    def get_setting(self, _key, _default):
        return self.value


def test_login_remote_maintenance_accepts_canonical_boolean_forms():
    for value in (True, 1, "1", "true", "TRUE", "yes", "on"):
        notice = LoginRemoteNoticeService.evaluate(
            {
                "remote_maintenance_enabled": value,
                "remote_maintenance_message": "Maintenance",
            }
        )
        assert notice.message == "Maintenance"
        assert notice.severity == "warning"


def test_usage_zero_filter_accepts_canonical_boolean_forms():
    for value in (True, 1, "1", "true", "TRUE", "yes", "on"):
        assert UsageWorkspaceService.hide_total_zero_enabled(_Settings(value)) is True
    for value in (False, 0, "0", "false", "off", ""):
        assert UsageWorkspaceService.hide_total_zero_enabled(_Settings(value)) is False
