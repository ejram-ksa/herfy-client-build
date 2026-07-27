from __future__ import annotations

import getpass
import hashlib
import os
import socket
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable


_PROTOCOL_PREFIX = "HERFY_ACTIVATE/1"
_PORT_MIN = 42000
_PORT_SPAN = 20000
_PORT_CANDIDATES = 8


@dataclass(frozen=True, slots=True)
class SingleInstanceResult:
    primary: bool
    notified_existing: bool = False


@dataclass(slots=True)
class RuntimeInstanceLease:
    """Compatibility facade used by the application bootstrap."""

    acquired: bool
    lock: "SingleInstanceGuard"
    _activation_bridge: Any = None

    def start_server(self, window: Any) -> None:
        """Attach foreground activation after the Qt window exists.

        The TCP listener runs on a Python worker thread.  When Qt is present,
        activation is marshalled to the GUI thread through a Qt signal.  The
        non-Qt fallback is retained for headless integration tests.
        """

        try:
            from PyQt5.QtCore import QObject, pyqtSignal

            class _ActivationBridge(QObject):
                requested = pyqtSignal()

            bridge = _ActivationBridge(window if isinstance(window, QObject) else None)
            bridge.requested.connect(lambda: reveal_window(window))
            self._activation_bridge = bridge
            self.lock.set_on_activate(bridge.requested.emit)
        except (ImportError, TypeError, RuntimeError):
            self.lock.set_on_activate(lambda: reveal_window(window))


class SingleInstanceGuard:
    """Per-user single-instance guard over authenticated localhost TCP.

    Multiple Windows users or terminal sessions do not block one another: the
    stable endpoint derives from both the application id and the current user
    identity.  Several deterministic candidate ports are used so an unrelated
    localhost service cannot make the client exit as a false second instance.
    """

    def __init__(
        self,
        app_id: str,
        *,
        on_activate: Callable[[], None] | None = None,
        host: str = "127.0.0.1",
        user_scope: str | None = None,
    ) -> None:
        app_id = str(app_id or "").strip()
        if not app_id:
            raise ValueError("app_id is required")
        if host != "127.0.0.1":
            raise ValueError("single-instance listener must bind to IPv4 localhost")

        self.app_id = app_id
        self.host = host
        self.user_scope = str(user_scope or _current_user_scope()).strip()
        if not self.user_scope:
            raise RuntimeError("unable to determine the current user scope")

        seed = f"{self.app_id}\0{self.user_scope}".encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        self._candidate_ports = _candidate_ports(digest)
        self.port = self._candidate_ports[0]
        self._activation_token = hashlib.sha256(
            digest + b"\0herfy-single-instance-activation"
        ).hexdigest()
        self._on_activate = on_activate or (lambda: None)
        self._callback_lock = threading.Lock()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._closed = False

    def set_on_activate(self, callback: Callable[[], None] | None) -> None:
        with self._callback_lock:
            self._on_activate = callback or (lambda: None)

    def acquire(self) -> SingleInstanceResult:
        if self._closed:
            raise RuntimeError("single-instance guard is already closed")
        if self._socket is not None:
            return SingleInstanceResult(primary=True)

        for port in self._candidate_ports:
            server = self._new_server_socket()
            try:
                server.bind((self.host, port))
                server.listen(4)
                server.settimeout(0.2)
            except OSError:
                server.close()
                if self._notify_port(port):
                    self.port = port
                    return SingleInstanceResult(
                        primary=False,
                        notified_existing=True,
                    )
                continue

            self.port = port
            self._socket = server
            self._thread = threading.Thread(
                target=self._serve,
                name="herfy-single-instance",
                daemon=True,
            )
            self._thread.start()
            return SingleInstanceResult(primary=True)

        raise RuntimeError(
            "unable to acquire a single-instance endpoint; all candidates are busy"
        )

    def notify_existing(self) -> bool:
        return any(self._notify_port(port) for port in self._candidate_ports)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(1.0)

    def wait(self, timeout_seconds: float = 1.0) -> bool:
        thread = self._thread
        if thread is None:
            return True
        thread.join(max(0.0, float(timeout_seconds)))
        return not thread.is_alive()

    def _new_server_socket(self) -> socket.socket:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform.startswith("win") and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return server

    def _activation_message(self) -> bytes:
        return f"{_PROTOCOL_PREFIX} {self._activation_token}\n".encode("ascii")

    def _notify_port(self, port: int) -> bool:
        try:
            with socket.create_connection((self.host, port), timeout=0.5) as client:
                client.settimeout(0.5)
                client.sendall(self._activation_message())
                return client.recv(16).strip() == b"OK"
        except OSError:
            return False

    def _serve(self) -> None:
        sock = self._socket
        if sock is None:
            return
        expected = self._activation_message().strip()
        while not self._stop.is_set():
            try:
                client, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with client:
                try:
                    client.settimeout(0.5)
                    message = client.recv(512).strip()
                    if message != expected:
                        client.sendall(b"DENIED\n")
                        continue
                    with self._callback_lock:
                        callback = self._on_activate
                    callback()
                    client.sendall(b"OK\n")
                except (OSError, RuntimeError, TypeError, ValueError):
                    continue


def _candidate_ports(digest: bytes) -> tuple[int, ...]:
    ports: list[int] = []
    counter = 0
    material = digest
    while len(ports) < _PORT_CANDIDATES:
        if counter and counter % 16 == 0:
            material = hashlib.sha256(material).digest()
        offset = (counter % 16) * 2
        candidate = _PORT_MIN + int.from_bytes(
            material[offset : offset + 2], "big"
        ) % _PORT_SPAN
        if candidate not in ports:
            ports.append(candidate)
        counter += 1
    return tuple(ports)


def _windows_user_sid() -> str | None:
    """Return the current Windows access-token SID with 64-bit-safe ctypes declarations."""

    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _SidAndAttributes(ctypes.Structure):
            _fields_ = [
                ("Sid", ctypes.c_void_p),
                ("Attributes", wintypes.DWORD),
            ]

        class _TokenUser(ctypes.Structure):
            _fields_ = [("User", _SidAndAttributes)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

        token_query = 0x0008
        token_user = 1
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
        ):
            return None
        try:
            needed = wintypes.DWORD(0)
            advapi32.GetTokenInformation(
                token, token_user, None, 0, ctypes.byref(needed)
            )
            if not needed.value:
                return None
            buffer = ctypes.create_string_buffer(needed.value)
            if not advapi32.GetTokenInformation(
                token,
                token_user,
                buffer,
                needed.value,
                ctypes.byref(needed),
            ):
                return None
            token_user_data = ctypes.cast(
                buffer, ctypes.POINTER(_TokenUser)
            ).contents
            if not token_user_data.User.Sid:
                return None
            sid_text = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(
                token_user_data.User.Sid, ctypes.byref(sid_text)
            ):
                return None
            try:
                return str(sid_text.value or "").strip() or None
            finally:
                kernel32.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        finally:
            kernel32.CloseHandle(token)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _current_user_scope() -> str:
    sid = _windows_user_sid()
    if sid:
        return f"sid:{sid}"
    if hasattr(os, "getuid"):
        try:
            return f"uid:{os.getuid()}"
        except OSError:
            pass
    domain = str(os.environ.get("USERDOMAIN") or "").strip()
    username = str(os.environ.get("USERNAME") or getpass.getuser() or "").strip()
    return f"name:{domain}\\{username}" if domain else f"name:{username}"


def acquire_runtime(arguments: Iterable[str] | None = None) -> RuntimeInstanceLease:
    """Acquire the canonical application instance for the current OS user."""

    del arguments  # Startup flags do not bypass the one-instance invariant.
    from runtime.shared.settings.config import APP_DESKTOP_APP_ID

    guard = SingleInstanceGuard(APP_DESKTOP_APP_ID)
    result = guard.acquire()
    return RuntimeInstanceLease(acquired=result.primary, lock=guard)


def reveal_window(window: Any) -> None:
    """Restore and activate a Qt-like window without importing Qt eagerly."""

    if window is None:
        return
    is_minimized = getattr(window, "isMinimized", None)
    show_normal = getattr(window, "showNormal", None)
    if callable(is_minimized) and callable(show_normal) and is_minimized():
        show_normal()
    show = getattr(window, "show", None)
    if callable(show):
        show()
    raise_window = getattr(window, "raise_", None)
    if callable(raise_window):
        raise_window()
    activate = getattr(window, "activateWindow", None)
    if callable(activate):
        activate()


def cleanup(window: Any, lock: Any) -> None:
    """Release the instance endpoint exactly once during shutdown."""

    del window
    close = getattr(lock, "close", None)
    if callable(close):
        close()
