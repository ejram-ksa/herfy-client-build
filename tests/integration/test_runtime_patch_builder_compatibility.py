from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from runtime.bootstrap.runtime import update_agent

ROOT = Path(__file__).resolve().parents[2]


def _load_tool(name: str):
    path = ROOT / "build" / "release" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime_manifest_tool = _load_tool("build_runtime_manifest")
runtime_patch_tool = _load_tool("build_runtime_patch")


def _create_runtime(root: Path) -> None:
    files = {
        update_agent.APP_EXE_NAME: b"client",
        update_agent.AGENT_EXE_NAME: b"agent",
        "version.json": json.dumps({"app_version": "2.18.1"}).encode("utf-8"),
        "resources/theme.qss": b"QWidget {}",
        "resources/i18n/ar.json": b"{}",
        "resources/i18n/en.json": b"{}",
        "PyQt5/Qt5/bin/Qt5Core.dll": b"dll",
    }
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def test_runtime_patch_builder_output_is_accepted_by_canonical_agent(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    _create_runtime(runtime_root)

    manifest = runtime_manifest_tool.build_manifest(runtime_root)
    output = tmp_path / "runtime.zip"
    runtime_patch_tool.build_runtime_patch(runtime_root, output, "2.18.1")

    assert manifest.read_text(encoding="utf-8").splitlines() == sorted(
        manifest.read_text(encoding="utf-8").splitlines()
    )
    update_agent._validate_patch_zip(output)


def test_runtime_patch_builder_rejects_source_artifacts(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    _create_runtime(runtime_root)
    (runtime_root / "leaked.py").write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Source/cache artifact"):
        runtime_manifest_tool.build_manifest(runtime_root)


def test_runtime_patch_builder_rejects_case_insensitive_path_collision(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    _create_runtime(runtime_root)
    (runtime_root / "Data").mkdir()
    (runtime_root / "data").mkdir()
    (runtime_root / "Data/item.dat").write_bytes(b"one")
    (runtime_root / "data/ITEM.dat").write_bytes(b"two")
    with pytest.raises(RuntimeError, match="Case-insensitive duplicate"):
        runtime_manifest_tool.build_manifest(runtime_root)
