from __future__ import annotations

import ast
from pathlib import Path

from runtime.infrastructure.network import http

ROOT = Path(__file__).resolve().parents[2]


def test_http_timeout_separates_connect_and_read(monkeypatch):
    monkeypatch.setattr(http, "get_http_timeout_seconds", lambda: 25.0)
    assert http.current_http_timeout() == (5.0, 25.0)


def test_http_timeout_keeps_small_config_valid(monkeypatch):
    monkeypatch.setattr(http, "get_http_timeout_seconds", lambda: 3.0)
    assert http.current_http_timeout() == (3.0, 3.0)


def test_live_scheduler_uses_nonblocking_dispatch():
    source = (ROOT / "runtime/services/lifecycle/background_scheduler.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    run_method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_run"
    )
    calls = {
        node.func.attr
        for node in ast.walk(run_method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "dispatch_due_once" in calls
    assert "run_due_once" not in calls


def test_startup_does_not_publish_false_offline_before_first_result():
    source = (ROOT / "runtime/presentation/main_window/window.py").read_text(
        encoding="utf-8"
    )
    block = source[source.index("def _initialize_status_widgets"):source.index("def _initialize_timers")]
    assert "Checking connection..." in block
    assert "self._set_cloud_state(False)" not in block
