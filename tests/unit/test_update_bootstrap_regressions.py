from __future__ import annotations

import ast
from pathlib import Path

import runtime.application.services.updates as updates


def test_update_manager_reads_upgrade_plan_from_bootstrap_payload(monkeypatch):
    calls = []

    def fake_fetch(path, **kwargs):
        calls.append(path)
        if path == "/meta/client-bootstrap":
            return {
                "upgrade_plan": {
                    "current_version": "2.18.1",
                    "target_version": "2.18.2",
                    "available": True,
                    "download_url": "/updates/2.18.2/setup.exe",
                    "sha256": "a" * 64,
                    "size": 123,
                }
            }
        raise AssertionError(f"unexpected fallback request: {path}")

    monkeypatch.setattr("runtime.application.services.updates.service.api_fetch_json", fake_fetch)
    manager = updates.UpdateManager(
        "2.18.1",
        base_url="https://updates.example",
        api_base_url="https://api.example",
    )
    info = manager.fetch()

    assert info.available is True
    assert info.latest == "2.18.2"
    assert info.url.endswith("/updates/2.18.2/setup.exe")
    assert calls == ["/meta/client-bootstrap"]


def test_runtime_modules_are_not_used_as_mapping_objects():
    root = Path(__file__).resolve().parents[2] / "runtime"
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get":
                continue
            owner = node.func.value
            parts = []
            while isinstance(owner, ast.Attribute):
                parts.append(owner.attr)
                owner = owner.value
            if isinstance(owner, ast.Name):
                parts.append(owner.id)
            qualified = ".".join(reversed(parts))
            if qualified == "runtime" or qualified.startswith("runtime."):
                violations.append(f"{path.relative_to(root.parent)}:{node.lineno}:{qualified}.get")
    assert violations == []
