from __future__ import annotations
import json
import logging
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.settings.messages import canonical_error_message
from runtime.infrastructure.network.admin_api import RemoteApiAdminMixin
from runtime.infrastructure.network.cache_api import RemoteApiCacheMixin, fetch_client_bootstrap
from runtime.infrastructure.network.realtime import RemoteRealtimeMixin
from runtime.infrastructure.network.tracking_api import CloudTrackingService
from runtime.infrastructure.network.tracking_api import RemoteApiTrackingMixin
from runtime.infrastructure.network.http import redact_url_for_log

logger = logging.getLogger(__name__)
__all__ = ["ApiClient", "fetch_client_bootstrap"]


class ApiClient(
    RemoteApiCacheMixin,
    RemoteApiAdminMixin,
    RemoteApiTrackingMixin,
    RemoteRealtimeMixin,
    CloudTrackingService,
):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_remote_cache()
        logger.info(
            "ApiClient initialized with base_url: %s", redact_url_for_log(self.base_url)
        )

    def _safe_json(self, response) -> dict:
        try:
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    canonical_error_message("malformed_response")
                ) from exc
            except SERVICE_OPERATION_EXCEPTIONS as exc:
                raise RuntimeError(canonical_error_message("invalid_response")) from exc
            return data if isinstance(data, dict) else {}
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
