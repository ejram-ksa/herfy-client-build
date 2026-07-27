from __future__ import annotations
from typing import Any
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.strings import normalize_text
from runtime.infrastructure.network.http import api_fetch_json, get_server_base_url
import logging
import threading
import time
from runtime.shared.concurrency import wait_for_inflight_event
from dataclasses import asdict, is_dataclass

logger = logging.getLogger(__name__)


def fetch_client_bootstrap(
    client_version: str, *, base_url: str | None = None
) -> dict[str, Any]:
    payload = api_fetch_json(
        "/meta/client-bootstrap",
        base_url=base_url or get_server_base_url(),
        params={"client_version": client_version},
    )
    return payload if isinstance(payload, dict) else {}


class RemoteApiCacheMixin:

    def init_remote_cache(self) -> None:
        self._request_lock = threading.RLock()
        self._memo: dict[str, tuple[float, Any]] = {}
        self._inflight_cache_events: dict[str, threading.Event] = {}
        self._pull_lock = threading.Lock()
        self._items_truncated = False

    def _cached(self, key: str, ttl_seconds: float, loader):
        now = time.monotonic()
        should_load = False
        with self._request_lock:
            cached = self._memo.get(key)
            if cached and now - cached[0] <= ttl_seconds:
                return cached[1]
            loader_event = self._inflight_cache_events.get(key)
            if loader_event is None:
                loader_event = threading.Event()
                self._inflight_cache_events[key] = loader_event
                should_load = True
        if not should_load:
            wait_for_inflight_event(
                loader_event,
                timeout_seconds=max(
                    5.0, min(15.0, float(ttl_seconds) if ttl_seconds else 5.0)
                ),
                logger_=logger,
                context=f"ApiClient._cached[{key}]",
            )
            with self._request_lock:
                cached = self._memo.get(key)
                if cached and time.monotonic() - cached[0] <= ttl_seconds:
                    return cached[1]
                stale_cached = self._memo.get(key)
            if stale_cached:
                logger.debug(
                    "ApiClient._cached returning stale memoized value for %s after wait timeout",
                    key,
                )
                return stale_cached[1]
            logger.debug(
                "ApiClient._cached skipped duplicate network load while another worker owns it: %s",
                key,
            )
            return []
        try:
            value = loader()
            with self._request_lock:
                self._memo[key] = (time.monotonic(), value)
            return value
        finally:
            with self._request_lock:
                event = self._inflight_cache_events.pop(key, None)
                if event is not None:
                    event.set()

    def _invalidate_prefix(self, prefix: str) -> None:
        with self._request_lock:
            for key in list(self._memo.keys()):
                if key.startswith(prefix):
                    self._memo.pop(key, None)

    def _require_branch(self, branch_id: str | None) -> str:
        branch = normalize_text(branch_id)
        if not branch:
            raise RuntimeError("Branch is required")
        return branch

    def invalidate_tracking_cache(self, branch: str | None = None) -> None:
        branch_key = normalize_text(branch).lower() if branch else ""
        with self._request_lock:
            for key in list(self._memo.keys()):
                if key.startswith("items:") and (
                    not branch_key or key in {f"items:{branch_key}", "items:all"}
                ):
                    self._memo.pop(key, None)


def _user_to_dict(user: Any) -> dict[str, Any]:
    if user is None:
        return {}
    if isinstance(user, dict):
        return user
    if is_dataclass(user):
        try:
            return asdict(user)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("_user_to_dict fallback failed", exc_info=True)
    data: dict[str, Any] = {}
    fields = (
        "username",
        "role",
        "branches",
        "branch_scope",
        "area_scope",
        "uid",
        "active_branch",
        "permissions",
        "scope",
        "area_id",
        "area_manager_id",
        "assigned_branch_ids",
        "must_change_password",
        "is_active",
        "temporary_manager",
    )
    for key in fields:
        try:
            if hasattr(user, key):
                data[key] = getattr(user, key)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("_user_to_dict fallback failed", exc_info=True)
    return data
