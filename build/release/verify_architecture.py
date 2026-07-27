from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_MODULE_FILES = {
    "ui/shell.py",
    "ui/shell_cloud.py",
    "presentation/logic.py",
}
FORBIDDEN_IMPORTS = {"runtime.presentation.logic", "runtime.presentation.shell", "runtime.presentation.shell_cloud"}


def imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def main() -> int:
    for relative in FORBIDDEN_MODULE_FILES:
        if (ROOT / relative).exists():
            raise RuntimeError(f"Obsolete architecture file remains: {relative}")
    violations: list[str] = []
    for path in ROOT.rglob("*.py"):
        if "release" in path.parts or "__pycache__" in path.parts:
            continue
        bad = sorted(imported_names(path) & FORBIDDEN_IMPORTS)
        if bad:
            violations.append(f"{path.relative_to(ROOT)} -> {', '.join(bad)}")
    if violations:
        raise RuntimeError("Obsolete imports remain:\n" + "\n".join(violations))
    print("HERFY_ARCHITECTURE_OK obsolete_shell=absent cloud_port=runtime.application.ports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
