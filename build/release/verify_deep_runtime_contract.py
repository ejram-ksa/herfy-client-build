from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import logging
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

from validation_result import format_validation_result

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _qt_available() -> bool:
    return importlib.util.find_spec("PyQt5") is not None


def _assert_python_sources() -> tuple[int, int]:
    files = sorted(ROOT.rglob("*.py"))
    total_lines = 0
    for path in files:
        relative_parts = set(path.relative_to(ROOT).parts)
        if relative_parts & {"build", "dist", "output", "publish", "__pycache__"}:
            continue
        source = path.read_text(encoding="utf-8-sig")
        total_lines += len(source.splitlines())
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defaults = list(node.args.defaults) + [
                    value for value in node.args.kw_defaults if value is not None
                ]
                _require(
                    not any(
                        isinstance(value, (ast.List, ast.Dict, ast.Set))
                        for value in defaults
                    ),
                    f"mutable function default: {path.relative_to(ROOT)}:{node.lineno}",
                )
            if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Tuple):
                nested_exception_groups = [
                    item.id
                    for item in node.type.elts
                    if isinstance(item, ast.Name) and item.id.endswith("_EXCEPTIONS")
                ]
                _require(
                    not nested_exception_groups,
                    "exception tuple was nested instead of expanded: "
                    f"{path.relative_to(ROOT)}:{node.lineno} "
                    f"groups={nested_exception_groups}",
                )
    return len(files), total_lines


def _assert_translation_isolation() -> None:
    from runtime.application.services.translations import format_days_text, get_language, set_language

    set_language("en")
    outputs: list[str] = []

    def worker(language: str) -> None:
        for _ in range(30):
            outputs.append(format_days_text(12, language_code=language))

    threads = [threading.Thread(target=worker, args=(code,)) for code in ("ar", "en")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    _require(get_language() == "en", "format_days_text mutated global language")
    _require(
        len(outputs) == 60 and all(outputs), "translation concurrency smoke failed"
    )


def _assert_http_safety() -> None:
    from runtime.shared.errors import RemoteRequestError
    from runtime.infrastructure.network.http import (
        _redirect_kwargs,
        _validated_redirect_target,
        redact_url_for_log,
    )

    clean = redact_url_for_log("https://user:pass@example.com:8443/a?token=secret#part")
    _require(clean == "https://example.com:8443/a", f"URL redaction failed: {clean}")
    _require(
        redact_url_for_log("https://example.com:bad/a") == "<invalid-url>",
        "invalid port leaked",
    )
    same = _redirect_kwargs(
        "https://example.com/a",
        "https://example.com/b",
        {
            "params": {"token": "x"},
            "headers": {"Authorization": "Bearer x"},
            "auth": ("u", "p"),
        },
    )
    _require(
        "params" not in same and "Authorization" in same["headers"],
        "same-origin redirect policy failed",
    )
    cross = _redirect_kwargs(
        "https://example.com/a",
        "https://other.example/b",
        {
            "params": {"token": "x"},
            "headers": {"Authorization": "Bearer x", "Cookie": "a=b", "X-Test": "ok"},
            "auth": ("u", "p"),
            "cookies": {"a": "b"},
        },
    )
    _require(
        cross.get("headers") == {"X-Test": "ok"},
        "cross-origin sensitive headers remained",
    )
    _require(
        "auth" not in cross and "cookies" not in cross and "params" not in cross,
        "cross-origin credentials remained",
    )
    for source, location in (
        ("https://example.com/a", "http://example.com/b"),
        ("https://example.com/a", "https://user:pass@example.com/b"),
    ):
        try:
            _validated_redirect_target(source, location)
        except RemoteRequestError:
            pass
        else:
            raise AssertionError(f"unsafe redirect accepted: {location}")


def _assert_http_log_redaction() -> None:
    import requests

    from runtime.shared.errors import RemoteRequestError
    from runtime.infrastructure.network import http as http_module

    class TimeoutSession:
        @staticmethod
        def request(*_args, **_kwargs):
            raise requests.Timeout(
                "request failed for https://example.com/a?token=super-secret"
            )

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    previous_level = http_module.logger.level
    http_module.logger.addHandler(handler)
    http_module.logger.setLevel(logging.INFO)
    try:
        try:
            http_module.request_with_retry(
                "GET",
                "https://example.com/a?token=super-secret",
                session=TimeoutSession(),
                max_retries=0,
            )
        except RemoteRequestError:
            pass
        else:
            raise AssertionError("timeout request unexpectedly succeeded")
    finally:
        http_module.logger.removeHandler(handler)
        http_module.logger.setLevel(previous_level)
    output = stream.getvalue()
    _require("super-secret" not in output, "HTTP logs leaked query credentials")


def _assert_realtime_worker_isolation() -> None:
    from runtime.infrastructure.network.realtime import RemoteRealtimeMixin, Signal
    from runtime.infrastructure.network.tracking_api import CloudTrackingService

    class Receiver:
        def __init__(self) -> None:
            self.calls = 0

        def callback(self, *_args) -> None:
            self.calls += 1

    receiver = Receiver()
    signal = Signal()
    signal.connect(receiver.callback)
    signal.disconnect(receiver.callback)
    signal.emit("ignored")
    _require(receiver.calls == 0, "bound realtime callback was not disconnected")

    signal.connect(receiver.callback)
    RemoteRealtimeMixin._replace_realtime_signal(signal, None)
    signal.emit("ignored")
    _require(receiver.calls == 0, "stale realtime callback remained connected")

    class RealtimeService(RemoteRealtimeMixin, CloudTrackingService):
        pass

    service = RealtimeService(base_url="https://example.com/api")
    old_event = service._rt_stop
    entered = threading.Event()

    def old_worker() -> None:
        entered.set()
        old_event.wait(2.0)

    thread = threading.Thread(target=old_worker, daemon=True)
    service._rt_thread = thread
    thread.start()
    _require(entered.wait(1.0), "realtime worker did not start")
    service._reset_realtime_worker()
    thread.join(timeout=1.0)
    _require(old_event.is_set(), "previous realtime event was not stopped")
    _require(not thread.is_alive(), "previous realtime worker did not terminate")
    _require(service._rt_stop is not old_event, "realtime stop Event was reused")
    _require(not service._rt_stop.is_set(), "new realtime Event started stopped")
    service.close()


def _assert_auth_runtime_contract() -> None:
    from runtime.application.services.auth import (
        _LOGIN_ALIAS_RETRY_STATUS_CODES,
        _normalized_expires_in,
    )

    _require(
        403 not in _LOGIN_ALIAS_RETRY_STATUS_CODES,
        "login access denial incorrectly retries an alias endpoint",
    )
    _require(_normalized_expires_in("bad") == 3600, "invalid expiry was accepted")
    _require(_normalized_expires_in(-1) == 3600, "negative expiry was accepted")
    _require(
        _normalized_expires_in(999999999) == 7 * 24 * 60 * 60,
        "expiry upper bound failed",
    )


def _assert_server_boolean_contracts() -> None:
    from runtime.domain.access import PermissionContext
    from runtime.domain.updates import parse_update_payload, resolve_download_url

    descriptor = parse_update_payload(
        {
            "latest_version": "1.0.0",
            "download_url": "https://updates.herfy.online/client.zip",
            "update_available": "false",
            "mandatory": "false",
            "current_supported": "false",
        },
        current_version="1.0.0",
        base_url="https://herfy.online",
    )
    _require(not descriptor.available, "string false enabled an update")
    _require(not descriptor.mandatory, "string false enabled mandatory update")
    _require(
        not descriptor.current_supported,
        "string false was not preserved for current_supported",
    )
    _require(
        not resolve_download_url("http://127.0.0.1/update.zip", "https://herfy.online"),
        "production update metadata was allowed to target a local HTTP host",
    )
    _require(
        resolve_download_url(
            "http://127.0.0.1/update.zip", "http://127.0.0.1:8000"
        ).startswith("http://127.0.0.1/"),
        "local development update host was unexpectedly rejected",
    )
    _require(
        not resolve_download_url(
            "https://user:pass@updates.herfy.online/update.zip",
            "https://herfy.online",
        ),
        "update URL credentials were accepted",
    )
    ctx = PermissionContext.from_payload(
        {
            "role": "branch_manager",
            "is_active": "false",
            "must_change_password": "false",
            "scope": {"all_branches": "false", "branches": ["1019"]},
            "permissions": ["tracking.view", "sync.pull"],
            "permission_source": "postgresql.role_permissions",
            "authority_revision": 1,
        }
    )
    _require(not ctx.is_active, "string false activated a user")
    _require(not ctx.must_change_password, "string false forced password change")
    _require(not ctx.scope.all_branches, "string false granted all-branch scope")


def _assert_remote_tracking_scope_contract() -> None:
    import threading

    from runtime.infrastructure.network.tracking_api import (
        RemoteTrackingItemsMixin,
        RemoteTrackingMetadataMixin,
        RemoteTrackingSyncMixin,
    )

    class Probe(RemoteTrackingMetadataMixin, RemoteTrackingSyncMixin):
        def __init__(self, user):
            self.user = user
            self._cursor = 7
            self._pull_lock = threading.RLock()
            self.pull_calls = []
            self.list_calls = []

        def list_items(self, branch_id=None, *, branch_filter=None):
            branch = branch_filter if branch_filter is not None else branch_id
            self.list_calls.append(branch)
            return [
                {
                    "id": f"{branch or 'all'}::1",
                    "branch": branch or "all",
                    "material_number": "100",
                    "expiry_date": "2026-08-01",
                }
            ]

        def pull_sync_changes(self, branch_id=None, *, cursor=None, branch_ids=None):
            self.pull_calls.append((branch_id, cursor, branch_ids))
            return {"changes": [], "cursor": cursor or 0}

        def invalidate_tracking_cache(self, _branch=None):
            return None

        def _invalidate_prefix(self, _prefix):
            return None

    restricted = Probe(
        {
            "scope": {"all_branches": "false", "branches": ["1019"]},
            "active_branch": "1019",
            "permissions": ["tracking.view", "sync.pull"],
            "permission_source": "postgresql.role_permissions",
        }
    )
    _require(
        not restricted._server_scope_all_branches(),
        "string false granted unrestricted remote tracking scope",
    )
    _require(
        restricted._server_scope_branch_ids() == ["1019"],
        "restricted remote tracking branches were not preserved",
    )
    snapshot = RemoteTrackingItemsMixin.snapshot_items(restricted)
    _require(
        [row.get("branch") for row in snapshot] == ["1019"]
        and restricted.list_calls == ["1019"],
        "restricted baseline snapshot used an unscoped request",
    )
    restricted.pull_now()
    _require(
        restricted.pull_calls == [(None, 7, ["1019"])],
        "restricted delta sync did not send the branch scope",
    )
    _require(
        restricted.pull_now("9999").get("scope_unavailable") is True,
        "out-of-scope explicit branch sync was not rejected",
    )

    missing = Probe(
        {
            "scope": {"all_branches": "false", "branches": []},
            "permissions": ["tracking.view", "sync.pull"],
            "permission_source": "postgresql.role_permissions",
        }
    )
    _require(
        RemoteTrackingItemsMixin.snapshot_items(missing) == []
        and not missing.list_calls,
        "missing scope fell back to an unrestricted baseline request",
    )
    _require(
        missing.pull_now().get("scope_unavailable") is True and not missing.pull_calls,
        "missing scope fell back to an unrestricted delta request",
    )

    unrestricted = Probe(
        {
            "scope": {"all_branches": "true", "branches": []},
            "permissions": ["tracking.view", "sync.pull"],
            "permission_source": "postgresql.role_permissions",
        }
    )
    _require(
        unrestricted._server_scope_all_branches(),
        "string true did not preserve unrestricted remote scope",
    )
    RemoteTrackingItemsMixin.snapshot_items(unrestricted)
    _require(
        unrestricted.list_calls == [None],
        "unrestricted baseline snapshot was unexpectedly narrowed",
    )


def _assert_tracking_scope_contract() -> None:
    from runtime.infrastructure.persistence.tracking_repo_sections import TrackingQueryRepositoryMixin

    class Cloud:
        def __init__(self) -> None:
            self.calls: list[str | None] = []

        def list_items(self, branch_filter=None):
            self.calls.append(branch_filter)
            return [
                {"id": "a", "branch": "1019"},
                {"id": "b", "branch": "9999"},
                {"id": "missing"},
            ]

    class Repo(TrackingQueryRepositoryMixin):
        cloud_list_cache_ttl_seconds = 60.0

        def __init__(self) -> None:
            self.cloud = Cloud()
            self._cloud_list_cache = {}
            self._cloud_cache_by_id = {}
            self._tracking_fetch_events = {}
            self._db_lock = threading.RLock()
            self._stored_name_cache = {"loaded": "yes"}
            self.allowed = ["1019"]
            self.active = ""

        def _cloud_service(self):
            return self.cloud

        def refresh_stored_products_from_cloud(self):
            return None

        def allowed_branches(self):
            return list(self.allowed)

        def can_view_all_branches(self):
            return False

        def get_active_branch(self):
            return self.active

        def _load_persisted_cloud_tracking_records(self, _key):
            return []

        def get_setting(self, _key, default=""):
            return default

        def _resolve_branch_case(self, branch):
            return str(branch)

        def _cloud_record_from_item(self, item):
            return dict(item)

        def _cache_cloud_record(self, item):
            return dict(item)

        def _persist_cloud_tracking_records(self, _rows):
            return None

    repo = Repo()
    rows = repo.fetch_tracked_products()
    _require(
        [row.get("branch") for row in rows] == ["1019"],
        "limited tracking scope accepted cross-branch or branchless records",
    )
    calls_before = list(repo.cloud.calls)
    _require(
        repo.fetch_tracked_products(branch_filter_override="9999") == [],
        "unauthorized explicit branch was not blocked",
    )
    _require(
        repo.cloud.calls == calls_before,
        "unauthorized explicit branch reached the cloud service",
    )
    repo.allowed = []
    _require(
        repo.fetch_tracked_products() == [], "empty branch scope did not fail closed"
    )


def _assert_admin_scope_contract() -> None:
    from runtime.domain.access import PermissionContext
    from runtime.application.services.admin import AdminService

    class Permissions:
        @staticmethod
        def filter_visible_users(users, permission_context):
            del permission_context
            return list(users)

    service = object.__new__(AdminService)
    service.permissions = Permissions()
    snapshot = {
        "regions": [{"region_id": "R1"}],
        "areas": [{"area_id": "A1", "region_id": "R1"}],
        "branches": [{"branch_id": "B1", "area_id": "A1"}],
        "users": [],
    }
    empty_scope = PermissionContext.from_payload(
        {
            "role": "branch_manager",
            "is_active": True,
            "scope": {},
            "permissions": [],
            "permission_source": "postgresql.role_permissions",
        }
    )
    filtered = service._filter_fallback_snapshot_for_context(
        dict(snapshot), empty_scope
    )
    _require(
        not filtered["regions"] and not filtered["areas"] and not filtered["branches"],
        "admin fallback metadata failed open for an empty non-system scope",
    )
    scoped = PermissionContext.from_payload(
        {
            "user_id": "one",
            "role": "branch_manager",
            "is_active": True,
            "scope": {"branches": ["B1"]},
            "permissions": ["admin.structure.read"],
            "permission_source": "postgresql.role_permissions",
            "authority_revision": 1,
        }
    )
    other = PermissionContext.from_payload(
        {
            "user_id": "two",
            "role": "branch_manager",
            "is_active": True,
            "scope": {"branches": ["B2"]},
            "permissions": ["admin.structure.read"],
            "permission_source": "postgresql.role_permissions",
            "authority_revision": 1,
        }
    )
    _require(
        service._permission_cache_key(scoped) != service._permission_cache_key(other),
        "admin cache key ignored identity or permission scope",
    )


def _assert_reconnect_flow() -> None:
    from runtime.application.services.sync import CloudReconnectFlowService

    offline = CloudReconnectFlowService.evaluate(
        online=False, previous_online=True, session_active=True
    )
    _require(
        not any(vars(offline).values()), "offline transition triggered reconnect work"
    )
    reconnect = CloudReconnectFlowService.evaluate(
        online=True, previous_online=False, session_active=True
    )
    _require(
        all(vars(reconnect).values()), "active-session reconnect did not refresh state"
    )
    hydrate = CloudReconnectFlowService.evaluate(
        online=True,
        previous_online=False,
        session_active=True,
        login_hydrate_pending=True,
    )
    _require(hydrate.should_invalidate_cache, "reconnect did not invalidate cache")
    _require(
        not hydrate.should_refresh_usage and not hydrate.should_emit_data_refresh,
        "login hydrate duplicated reconnect refresh",
    )


def _assert_atomic_storage() -> None:
    from runtime.shared.files import read_json_dict, write_bytes_atomic, write_json_dict
    from runtime.infrastructure.persistence.secure_store import read_secure_json
    from runtime.services.session import SessionStore

    with tempfile.TemporaryDirectory(prefix="herfy-deep-gate-") as temp:
        root = Path(temp)
        binary = root / "nested" / "payload.bin"
        write_bytes_atomic(binary, b"abc")
        _require(binary.read_bytes() == b"abc", "atomic byte write failed")
        json_path = root / "state.json"
        write_json_dict(json_path, {"ok": True})
        _require(read_json_dict(json_path) == {"ok": True}, "atomic JSON write failed")
        corrupt = root / "session.json"
        corrupt.write_text(
            '{"format":"secure-json-v1","method":"local-v1","payload":"***"}',
            encoding="utf-8",
        )
        _require(
            read_secure_json(corrupt) == {}, "corrupt secure snapshot was accepted"
        )
        from types import SimpleNamespace

        metadata = root / "session-metadata.json"
        secure = root / "session-secure.json"
        login_form = root / "login-form.json"
        store = SessionStore(metadata, secure, login_form)
        store.save(
            session=SimpleNamespace(uid="42", refresh_token="token-for-validation"),
            profile=SimpleNamespace(uid="42", username="H1074"),
            remember=True,
            saved_at="bad",
        )
        loaded = store.load_snapshot()
        _require(
            loaded is not None
            and loaded.username == "H1074"
            and loaded.remember is True
            and loaded.saved_at == 0,
            "remembered session snapshot was not normalized",
        )
        _require(
            "token-for-validation" not in metadata.read_text(encoding="utf-8")
            and "token-for-validation" not in secure.read_text(encoding="utf-8"),
            "session token leaked into a plaintext persisted file",
        )
        _require(not list(root.rglob("*.tmp")), "atomic write left temporary files")


def _assert_update_download_contract() -> None:
    from runtime.application.services.updates import (
        _MAX_UPDATE_DOWNLOAD_BYTES,
        download_response_to_target,
    )

    class Response:
        def __init__(self, chunks, content_length="") -> None:
            self._chunks = list(chunks)
            self.headers = {"content-length": content_length} if content_length else {}
            self.closed = False

        def iter_content(self, chunk_size):
            _require(chunk_size > 0, "invalid test download chunk size")
            yield from self._chunks

        def close(self):
            self.closed = True

    with tempfile.TemporaryDirectory(prefix="herfy-download-gate-") as temp:
        root = Path(temp)
        response = Response([b"abc"], content_length="4")
        try:
            download_response_to_target(
                response=response,
                target=root / "mismatch.zip",
                temp_dir=root,
                temp_prefix="mismatch_",
                expected_sha="",
                expected_size=3,
                progress_callback=None,
                package_label="patch package",
                chunk_size=2,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("conflicting update sizes were accepted")
        _require(response.closed, "rejected update response was not closed")

        response = Response([], content_length=str(_MAX_UPDATE_DOWNLOAD_BYTES + 1))
        try:
            download_response_to_target(
                response=response,
                target=root / "oversize.zip",
                temp_dir=root,
                temp_prefix="oversize_",
                expected_sha="",
                expected_size=0,
                progress_callback=None,
                package_label="patch package",
                chunk_size=2,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("oversized update declaration was accepted")
        _require(response.closed, "oversized update response was not closed")

        response = Response([b"a", b"bc"])
        target = download_response_to_target(
            response=response,
            target=root / "valid.zip",
            temp_dir=root,
            temp_prefix="valid_",
            expected_sha=hashlib.sha256(b"abc").hexdigest(),
            expected_size=3,
            progress_callback=None,
            package_label="patch package",
            chunk_size=2,
        )
        _require(target.read_bytes() == b"abc", "validated update write failed")
        _require(response.closed, "successful update response was not closed")
        _require(not list(root.glob("*.tmp")), "update download left temporary files")


def _assert_numeric_normalization_contract() -> None:
    from runtime.shared.numbers import format_plain_number, parse_excel_number, parse_plain_number
    from runtime.shared.objects import normalize_int
    from runtime.shared.settings.config import _safe_float

    for value in ("nan", "inf", "-inf", float("nan"), float("inf")):
        _require(
            normalize_int(value, 7) == 7, f"non-finite integer accepted: {value!r}"
        )
        _require(
            parse_plain_number(value) == 0.0,
            f"non-finite plain number accepted: {value!r}",
        )
        _require(
            parse_excel_number(value) == 0.0,
            f"non-finite Excel number accepted: {value!r}",
        )
        _require(
            _safe_float(value, 9.0) == 9.0,
            f"non-finite configuration float accepted: {value!r}",
        )
    _require(
        format_plain_number(float("inf")) == "inf",
        "non-finite number formatting raised",
    )


def _assert_single_instance_lock_contract() -> None:
    import os
    import threading
    import time

    from runtime.bootstrap.runtime.single_instance import SingleInstanceGuard

    app_id = f"HerfyClient.DeepGate.{os.getpid()}.{time.time_ns()}"
    activated = threading.Event()
    primary = SingleInstanceGuard(app_id, on_activate=activated.set)
    secondary = SingleInstanceGuard(app_id)
    try:
        first = primary.acquire()
        _require(first.primary, "first single-instance guard was not primary")
        second = secondary.acquire()
        _require(not second.primary, "second single-instance guard became primary")
        _require(second.notified_existing, "secondary instance did not notify primary")
        _require(activated.wait(1.0), "primary instance did not receive activation")
    finally:
        secondary.close()
        primary.close()
    _require(primary.wait(1.0), "single-instance listener did not stop")


def _assert_update_release_probe_contract() -> None:
    from runtime.bootstrap.runtime.update_agent import APP_EXE_NAME, _wait_for_target_release

    with tempfile.TemporaryDirectory(prefix="herfy-release-probe-") as temp:
        root = Path(temp)
        target = root / APP_EXE_NAME
        stale_probe = root / f".{APP_EXE_NAME}.rename_test"
        stale_probe.write_bytes(b"runtime")
        _wait_for_target_release(root, 1)
        _require(
            target.read_bytes() == b"runtime", "stale executable probe was not restored"
        )
        _require(
            not stale_probe.exists(), "stale executable probe remained after recovery"
        )
        _require(
            not (root / f".{APP_EXE_NAME}.write_test").exists(),
            "write probe remained after target release check",
        )


def _assert_payload_normalization_contract() -> None:
    from runtime.application.dto import change_operation
    from runtime.infrastructure.network.admin_api import AdminPayloadHelpers

    _require(
        change_operation({"deleted": "false"}) == "upsert",
        "string false was interpreted as a deletion flag",
    )
    _require(
        change_operation({"payload": {"is_deleted": "true"}}) == "delete",
        "string true deletion flag was ignored",
    )
    normalizer = object.__new__(AdminPayloadHelpers)
    payload = normalizer._normalize_admin_dashboard_payload(
        {"structure_mutation_contract_ready": "false"}
    )
    _require(
        not payload["structure_mutation_contract_ready"],
        "string false enabled the admin mutation contract",
    )


def _assert_external_payload_normalization() -> bool:
    """Validate server payload normalization; return whether Qt checks ran."""

    from runtime.infrastructure.persistence.tracking_cloud import (
        normalize_cloud_tracking_record,
    )
    from runtime.presentation.notifications import (
        NotificationMessageFormatter,
        build_expiry_toast_view_model,
    )
    from runtime.infrastructure.network.realtime import RemoteRealtimeMixin
    from runtime.application.services.admin import AdminService

    tracked = normalize_cloud_tracking_record({"quantity": "inf"})
    _require(tracked["quantity"] == 0, "non-finite cloud quantity was accepted")
    _require(
        RemoteRealtimeMixin._cursor_from_realtime_payload('{"cursor":"inf"}') == 0,
        "non-finite realtime cursor was accepted",
    )
    _require(
        RemoteRealtimeMixin._cursor_from_realtime_payload("123") == 123,
        "valid realtime cursor was rejected",
    )
    copied = AdminService._copy_snapshot(
        {"structure_mutation_contract_ready": "false"}
    )
    _require(
        not copied["structure_mutation_contract_ready"],
        "string false enabled copied admin mutation state",
    )
    formatter = NotificationMessageFormatter()
    _require(
        formatter.severity_rank({"severity_rank": "inf"}) == 0,
        "non-finite notification severity was accepted",
    )
    toast = build_expiry_toast_view_model(
        title="test",
        payload={"duration_s": "9999", "message": "summary"},
        duration_s=0,
    )
    _require(toast.duration_s == 60, "notification duration upper bound failed")

    if not _qt_available():
        return False

    from runtime.presentation.tables.usage_model import UsageModel
    from runtime.presentation.updates.update_flow_sections import (
        OnlineUpdateProgressMixin,
    )

    usage_row = UsageModel._normalize_row(
        {"total": "inf", "user_set": "false", "onhand": "9"}
    )
    _require(usage_row["total"] == 0.0, "non-finite usage total was accepted")
    _require(not usage_row["user_set"], "string false enabled usage user input")

    class Dialog:
        def __init__(self) -> None:
            self.value = -1

        def setLabelText(self, _value):
            return None

        def setStageText(self, _value):
            return None

        def setFooterText(self, _value):
            return None

        def setDetailText(self, _value):
            return None

        def setValue(self, value):
            self.value = value

    dialog = Dialog()
    OnlineUpdateProgressMixin()._apply_download_progress(
        dialog,
        "download",
        {"percent": "inf", "downloaded": "-5", "total": "nan"},
    )
    _require(dialog.value == 0, "invalid update progress was not normalized")
    return True


def _assert_update_package_safety() -> None:
    from runtime.bootstrap.runtime.update_agent import _validate_patch_zip

    with tempfile.TemporaryDirectory(prefix="herfy-patch-gate-") as temp:
        malicious = Path(temp) / "malicious.zip"
        with zipfile.ZipFile(malicious, "w") as package:
            package.writestr("../escape.txt", "blocked")
        try:
            _validate_patch_zip(malicious)
        except RuntimeError:
            pass
        else:
            raise AssertionError("update ZIP traversal member was accepted")


def _assert_tracking_startup_consistency_contract() -> None:
    import sqlite3
    import tempfile
    import threading

    from runtime.infrastructure.persistence.cache_sections import TrackingCacheRepositoryMixin
    from runtime.infrastructure.persistence.tracking_repo_sections import (
        TrackingUpdateValidation,
        validate_tracking_update_fields,
    )
    from runtime.domain.tracking_rows import deduplicate_tracking_records

    duplicate_rows = [
        {
            "id": "H1090::old-id",
            "doc_id": "old-id",
            "branch": "H1090",
            "material_number": "1020000003",
            "quantity": 9,
            "production_date": "2026-06-16",
            "expiry_date": "2026-06-16",
        },
        {
            "id": "H1090::new-id",
            "doc_id": "new-id",
            "branch": "H1090",
            "material_number": "1020000003",
            "quantity": 9,
            "production_date": "2026-06-16",
            "expiry_date": "2026-06-16",
        },
        {
            "id": "H1391::other-id",
            "doc_id": "other-id",
            "branch": "H1391",
            "material_number": "1020000003",
            "quantity": 3,
            "production_date": "2026-06-16",
            "expiry_date": "2026-06-22",
        },
    ]
    _require(
        len(deduplicate_tracking_records(duplicate_rows)) == 2,
        "logical tracking duplicates were not removed before display",
    )
    validation = validate_tracking_update_fields(3, "2026-07-01", "2026-07-10")
    _require(
        isinstance(validation, TrackingUpdateValidation)
        and validation.ok
        and validation.quantity == 3,
        "TrackingUpdateValidation is not constructible with validated fields",
    )

    class CacheRepo(TrackingCacheRepositoryMixin):
        def __init__(self, db_path: Path) -> None:
            self.db_path = db_path
            self._db_lock = threading.RLock()
            self._stored_name_cache = {}
            self._cloud_cache_by_id = {}
            self._cloud_list_cache = {}

        def _fresh_connection(self):
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

        @staticmethod
        def allowed_branches():
            return ["H1090", "H1391"]

        @staticmethod
        def can_view_all_branches():
            return True

    with tempfile.TemporaryDirectory(prefix="herfy-tracking-cache-") as temp:
        db_path = Path(temp) / "tracking.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE cloud_tracked_products(
              id TEXT PRIMARY KEY,
              branch TEXT DEFAULT '',
              material_number TEXT DEFAULT '',
              expiry_date TEXT DEFAULT '',
              payload TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """)
        conn.commit()
        conn.close()
        repo = CacheRepo(db_path)
        _require(
            repo._persist_cloud_tracking_records([duplicate_rows[0]]),
            "initial cache persist failed",
        )
        _require(
            repo._persist_cloud_tracking_records([duplicate_rows[1]]),
            "replacement cache persist failed",
        )
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM cloud_tracked_products").fetchone()[
            0
        ]
        stored_id = conn.execute("SELECT id FROM cloud_tracked_products").fetchone()[0]
        conn.close()
        _require(
            count == 1,
            "stale logical tracking row remained in SQLite cache",
        )
        _require(
            stored_id == "H1090::new-id",
            "new tracking identity did not replace stale cache",
        )

    startup_source = (ROOT / "runtime" / "bootstrap" / "runtime" / "app_bootstrap.py").read_text(
        encoding="utf-8"
    )
    _require(
        '_startup_setting("start_minimized_to_tray"' not in startup_source,
        "ordinary startup can still disappear due to a stale preference",
    )
    _require(
        "def _show_startup_window(window" in startup_source
        and "window.show()" in startup_source
        and "reveal_window(window)" in startup_source
        and "QTimer.singleShot(250" not in startup_source
        and "QTimer.singleShot(1200" not in startup_source,
        "foreground startup is not shown once through the canonical reveal path",
    )
    _require(
        '"--background"' in startup_source,
        "explicit background startup mode was lost",
    )
    _require(
        '"--minimized"' not in startup_source,
        "obsolete minimized startup can still hide an ordinary launch",
    )
    _require(
        "_ensure_background_runtime(window)" in startup_source
        and 'set_setting("enable_tray_background", "True")' in startup_source,
        "background/tray runtime is not enforced for the single running process",
    )
    sync_source = (ROOT / "runtime" / "application" / "services" / "sync" / "service.py").read_text(
        encoding="utf-8"
    )
    autostart_source = (
        ROOT / "runtime" / "services" / "windows" / "autostart_service.py"
    ).read_text(encoding="utf-8")
    _require(
        "def _autostart_launch_spec()" in sync_source
        and "AutostartService(" in sync_source
        and "WindowsRunRegistryBackend()" in sync_source
        and "('--background',)" in sync_source
        and "'--background')" in sync_source
        and '"--tray" if minimized' not in sync_source
        and "start_minimized_to_tray" not in sync_source
        and "subprocess.list2cmdline" in autostart_source
        and "import winreg" in autostart_source,
        "Windows startup is not delegated to the canonical background autostart service",
    )
    settings_source = (ROOT / "runtime" / "presentation" / "views" / "settings_page.py").read_text(
        encoding="utf-8"
    )
    _require(
        'self.widgets["start_with_windows"]' in settings_source
        and "start_minimized_to_tray" not in settings_source,
        "startup settings UI is incomplete or exposes hidden startup",
    )


def _assert_static_runtime_contracts() -> None:
    secure_source = (ROOT / "runtime" / "infrastructure" / "persistence" / "secure_store.py").read_text(encoding="utf-8")
    _require(
        "input_buffer = ctypes.create_string_buffer(raw)" in secure_source,
        "DPAPI input buffer lifetime guard missing",
    )
    _require(
        "entropy_buffer = ctypes.create_string_buffer(_PURPOSE)" in secure_source,
        "DPAPI entropy buffer lifetime guard missing",
    )
    _require(
        "kernel32.LocalFree.argtypes = [ctypes.c_void_p]" in secure_source,
        "DPAPI LocalFree pointer signature missing",
    )
    _require(
        "_CRYPTPROTECT_UI_FORBIDDEN = 0x1" in secure_source
        and "_CRYPTPROTECT_UI_FORBIDDEN," in secure_source,
        "DPAPI may display an interactive UI prompt",
    )
    _require(
        "Previous plaintext snapshots remain readable" not in secure_source
        and "return dict(payload)" not in secure_source,
        "plaintext secure-session fallback remains enabled",
    )
    _require(
        not (ROOT / "runtime" / "services" / "update").exists(),
        "duplicate non-canonical update service stack remains",
    )
    auth_source = (ROOT / "runtime" / "application" / "services" / "auth" / "service.py").read_text(
        encoding="utf-8"
    )
    _require(
        "Auth successful for user=" not in auth_source,
        "authentication logs expose the login identifier",
    )
    single_instance_source = (
        ROOT / "runtime" / "bootstrap" / "runtime" / "single_instance.py"
    ).read_text(encoding="utf-8")
    _require(
        "_current_user_scope()" in single_instance_source
        and "_windows_user_sid()" in single_instance_source,
        "single-instance endpoint is not scoped to the authenticated OS user",
    )
    _require(
        "SO_EXCLUSIVEADDRUSE" in single_instance_source
        and 'host: str = "127.0.0.1"' in single_instance_source,
        "single-instance listener is not exclusive and localhost-only on Windows",
    )
    _require(
        "HERFY_ACTIVATE/1" in single_instance_source
        and "client.recv(16).strip() == b\"OK\"" in single_instance_source,
        "single-instance activation handshake is not authenticated",
    )
    _require(
        "def acquire_runtime(" in single_instance_source
        and "def reveal_window(" in single_instance_source
        and "def cleanup(" in single_instance_source,
        "application bootstrap compatibility API is incomplete",
    )
    lifecycle_source = (
        ROOT / "runtime" / "presentation" / "main_window" / "action_sections" / "actions.py"
    ).read_text(encoding="utf-8")
    _require(
        "waitForDone" in lifecycle_source
        and "_drain_runtime_thread_pool" in lifecycle_source,
        "shutdown does not drain active workers before closing runtime resources",
    )
    admin_source = (ROOT / "runtime" / "presentation" / "views" / "admin_page.py").read_text(encoding="utf-8")
    _require(
        "QEvent.ScreenChangeInternal" not in admin_source,
        "unsafe direct Qt event constant returned",
    )


def main() -> int:
    files, lines = _assert_python_sources()
    _assert_translation_isolation()
    _assert_http_safety()
    _assert_http_log_redaction()
    _assert_realtime_worker_isolation()
    _assert_auth_runtime_contract()
    _assert_server_boolean_contracts()
    _assert_tracking_scope_contract()
    _assert_remote_tracking_scope_contract()
    _assert_admin_scope_contract()
    _assert_reconnect_flow()
    _assert_atomic_storage()
    _assert_update_download_contract()
    _assert_numeric_normalization_contract()
    _assert_single_instance_lock_contract()
    _assert_update_release_probe_contract()
    _assert_payload_normalization_contract()
    qt_payload_checks = _assert_external_payload_normalization()
    _assert_update_package_safety()
    _assert_tracking_startup_consistency_contract()
    _assert_static_runtime_contracts()
    print(
        "HERFY_DEEP_RUNTIME_CONTRACT_OK "
        f"python_files={files} python_lines={lines} "
        "translation=ok http=ok realtime=ok auth=ok booleans=ok "
        "tracking_scope=ok admin_scope=ok reconnect=ok storage=ok "
        "download=ok numbers=ok lock=ok release_probe=ok payloads=ok "
        "external_payloads=ok updater=ok tracking_startup=ok remote_scope=ok "
        f"qt={'ok' if qt_payload_checks else 'SKIPPED(PyQt5-unavailable)'}"
    )
    print(
        format_validation_result(
            "deep-runtime-contract",
            "passed" if qt_payload_checks else "partial",
            f"python-files={files},python-lines={lines},qt={'ok' if qt_payload_checks else 'not-run'}",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
