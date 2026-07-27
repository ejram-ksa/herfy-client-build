from __future__ import annotations

from pathlib import Path

from runtime.services.lifecycle import close_runtime_client

ROOT = Path(__file__).resolve().parents[2]


class _Client:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def close(self) -> None:
        self.calls.append("close")

    def shutdown(self) -> None:
        self.calls.append("shutdown")

    def stop_realtime(self) -> None:
        self.calls.append("stop_realtime")


class _ShutdownOnly:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def shutdown(self) -> None:
        self.calls.append("shutdown")

    def stop_realtime(self) -> None:
        self.calls.append("stop_realtime")


class _RealtimeOnly:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def stop_realtime(self) -> None:
        self.calls.append("stop_realtime")


def test_client_cleanup_uses_one_terminal_method_only():
    client = _Client()
    assert close_runtime_client(client) == "close"
    assert client.calls == ["close"]


def test_client_cleanup_falls_back_without_double_release():
    shutdown = _ShutdownOnly()
    realtime = _RealtimeOnly()
    assert close_runtime_client(shutdown) == "shutdown"
    assert shutdown.calls == ["shutdown"]
    assert close_runtime_client(realtime) == "stop_realtime"
    assert realtime.calls == ["stop_realtime"]
    assert close_runtime_client(None) == ""


def test_logout_and_shutdown_use_the_canonical_client_cleanup_boundary():
    session_source = (
        ROOT / "runtime/presentation/main_window/session_sections/session.py"
    ).read_text(encoding="utf-8")
    actions_source = (
        ROOT / "runtime/presentation/main_window/action_sections/actions.py"
    ).read_text(encoding="utf-8")
    bootstrap_source = (
        ROOT / "runtime/bootstrap/runtime/app_bootstrap.py"
    ).read_text(encoding="utf-8")
    cloud_source = (
        ROOT / "runtime/presentation/main_window/cloud_sections/cloud_runtime.py"
    ).read_text(encoding="utf-8")

    logout = session_source[session_source.index("def logout"):]
    logout = logout[: logout.index("def show_login")]
    assert "close_runtime_client(" in logout
    assert ".stop_realtime()" not in logout

    shutdown = actions_source[actions_source.index("def _shutdown_runtime_resources"):]
    shutdown = shutdown[: shutdown.index("def close_app_completely")]
    assert "close_runtime_client(api_client)" in shutdown
    assert "close_client = getattr" not in shutdown

    fallback = bootstrap_source[bootstrap_source.index("def _shutdown_cleanup"):]
    fallback = fallback[: fallback.index("def run_gui_application")]
    assert "close_runtime_client(api_client)" in fallback
    assert "api_client.stop_realtime()" not in fallback

    login = cloud_source[cloud_source.index("def on_login_success"):]
    login = login[: login.index("def _hydrate_login_state")]
    assert "close_runtime_client(previous_client)" in login
