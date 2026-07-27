from __future__ import annotations
from typing import Any
from runtime.domain.runtime_state import RuntimeStateCore
from runtime.domain.access import PermissionContext

try:
    from PyQt5.QtCore import QObject, pyqtSignal
except ModuleNotFoundError:

    class _SignalInstance:

        def __init__(self) -> None:
            """Initialize the instance."""
            self._callbacks: list[Any] = []

        def connect(self, callback: Any) -> None:
            if callable(callback) and callback not in self._callbacks:
                self._callbacks.append(callback)

        def disconnect(self, callback: Any | None = None) -> None:
            if callback is None:
                self._callbacks.clear()
                return
            try:
                self._callbacks.remove(callback)
            except ValueError:
                return

        def emit(self, *args: Any, **kwargs: Any) -> None:
            for callback in list(self._callbacks):
                callback(*args, **kwargs)

    class _SignalDescriptor:

        def __init__(self, *_types: Any) -> None:
            self._name = ""

        def __set_name__(self, _owner: type, name: str) -> None:
            self._name = f"__signal_{name}"

        def __get__(self, instance: Any, _owner: type | None = None) -> Any:
            if instance is None:
                return self
            signal = instance.__dict__.get(self._name)
            if signal is None:
                signal = _SignalInstance()
                instance.__dict__[self._name] = signal
            return signal

    class QObject:

        def __init__(self, parent: Any | None = None) -> None:
            self._qt_parent = parent

    def pyqtSignal(*types: Any) -> _SignalDescriptor:
        return _SignalDescriptor(*types)


class AppState(QObject, RuntimeStateCore):
    session_changed = pyqtSignal(object)
    user_changed = pyqtSignal(object)
    permissions_changed = pyqtSignal(object)
    branch_changed = pyqtSignal(str)
    connection_changed = pyqtSignal(bool, str)
    cache_changed = pyqtSignal(str, object)
    api_client_changed = pyqtSignal(object)
    data_changed = pyqtSignal(str, object)
    item_updated = pyqtSignal(str, object)
    item_deleted = pyqtSignal(str, object)

    def __init__(self, parent: QObject | None = None):
        QObject.__init__(self, parent)
        self._init_runtime_state()

    def _emit_session_changed(self, session: Any) -> None:
        self.session_changed.emit(session)

    def _emit_user_changed(self, profile: Any) -> None:
        self.user_changed.emit(profile)

    def _emit_permissions_changed(self, permission_context: PermissionContext) -> None:
        self.permissions_changed.emit(permission_context)

    def _emit_branch_changed(self, branch: str) -> None:
        self.branch_changed.emit(branch)

    def _emit_connection_changed(self, online: bool, message: str) -> None:
        self.connection_changed.emit(online, message)

    def _emit_cache_changed(self, key: str, value: Any) -> None:
        self.cache_changed.emit(key, value)

    def _emit_api_client_changed(self, api_client: Any) -> None:
        self.api_client_changed.emit(api_client)

    @staticmethod
    def _clean_domain(domain: str) -> str:
        return str(domain or "").strip().lower()

    def emit_data_changed(self, domain: str, payload: Any = None) -> None:
        self.data_changed.emit(self._clean_domain(domain), payload)

    def _emit_item_change(self, signal, domain: str, payload: Any = None) -> None:
        signal.emit(self._clean_domain(domain), payload)
        self.emit_data_changed(domain, payload)

    def emit_item_updated(self, domain: str, payload: Any = None) -> None:
        self._emit_item_change(self.item_updated, domain, payload)

    def emit_item_deleted(self, domain: str, payload: Any = None) -> None:
        self._emit_item_change(self.item_deleted, domain, payload)
