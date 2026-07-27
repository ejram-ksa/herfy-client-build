from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
MAX_INIT_BYTES = 4096

FORBIDDEN_PARALLEL_ROOTS = (
    RUNTIME / "data",
    RUNTIME / "services" / "notifications",
    RUNTIME / "services" / "offline",
    RUNTIME / "services" / "sync",
    RUNTIME / "services" / "ui",
)
FORBIDDEN_DEAD_MODULES = (
    RUNTIME / "application" / "services" / "window_controller.py",
    RUNTIME / "version.py",
)

REQUIRED_SEMANTIC_MODULES = (
    RUNTIME / "application" / "ports" / "gateways.py",
    RUNTIME / "presentation" / "auth" / "login_controller.py",
    RUNTIME / "presentation" / "usage" / "compute_service.py",
    RUNTIME / "bootstrap" / "runtime" / "single_instance.py",
    RUNTIME / "shared" / "settings" / "runtime_migration.py",
    ROOT / "build" / "release" / "source_manifest.py",
    ROOT / "build" / "release" / "verify_source_manifest.py",
)
REQUIRED_SINGLE_INSTANCE_API = {
    "SingleInstanceGuard",
    "RuntimeInstanceLease",
    "acquire_runtime",
    "reveal_window",
    "cleanup",
}


def _dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def main() -> int:
    errors: list[str] = []

    for path in FORBIDDEN_PARALLEL_ROOTS:
        if path.exists():
            errors.append(f"obsolete parallel runtime root remains: {path.relative_to(ROOT)}")

    for path in FORBIDDEN_DEAD_MODULES:
        if path.exists():
            errors.append(f"obsolete dead module remains: {path.relative_to(ROOT)}")

    for path in REQUIRED_SEMANTIC_MODULES:
        if not path.is_file():
            errors.append(f"required semantic module is missing: {path.relative_to(ROOT)}")

    for path in sorted(RUNTIME.rglob("__init__.py")):
        source = path.read_text(encoding="utf-8-sig")
        if path.stat().st_size > MAX_INIT_BYTES:
            errors.append(
                "implementation-heavy package initializer: "
                f"{path.relative_to(ROOT)} bytes={path.stat().st_size}"
            )
        if "vars(_implementation)" in source or "globals()[_name]" in source:
            errors.append(
                "dynamic package facade is forbidden: "
                f"{path.relative_to(ROOT)}"
            )

    verifier_path = Path(__file__).resolve()
    for path in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or path.resolve() == verifier_path:
            continue
        source = path.read_text(encoding="utf-8-sig")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            errors.append(f"syntax error: {path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")
            continue

        imported: set[tuple[object, ...]] = set()
        logger_assignments = 0
        for top_level in tree.body:
            if isinstance(top_level, ast.Import):
                for alias in top_level.names:
                    key = ("import", alias.name, alias.asname)
                    if key in imported:
                        errors.append(
                            "duplicate top-level import: "
                            f"{path.relative_to(ROOT)}:{top_level.lineno}: {alias.name}"
                        )
                    imported.add(key)
            elif isinstance(top_level, ast.ImportFrom):
                for alias in top_level.names:
                    key = (
                        "from",
                        top_level.level,
                        top_level.module,
                        alias.name,
                        alias.asname,
                    )
                    if key in imported:
                        errors.append(
                            "duplicate top-level import: "
                            f"{path.relative_to(ROOT)}:{top_level.lineno}: "
                            f"{top_level.module}.{alias.name}"
                        )
                    imported.add(key)
            elif isinstance(top_level, ast.Assign):
                if any(
                    isinstance(target, ast.Name) and target.id == "logger"
                    for target in top_level.targets
                ):
                    logger_assignments += 1
        if logger_assignments > 1:
            errors.append(
                "duplicate module logger declarations: "
                f"{path.relative_to(ROOT)} count={logger_assignments}"
            )

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                dotted = _dotted_name(node)
                if dotted.startswith("runtime.bootstrap.app."):
                    errors.append(
                        "module-qualified local QApplication reference: "
                        f"{path.relative_to(ROOT)}:{node.lineno}: {dotted}"
                    )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if value.startswith("runtime.shared.settings.") and value != "runtime.shared.settings.ini":
                    errors.append(
                        "corrupted settings key or filename: "
                        f"{path.relative_to(ROOT)}:{node.lineno}: {value!r}"
                    )

    function_bodies: dict[str, list[tuple[Path, str, int]]] = defaultdict(list)
    for path in sorted(RUNTIME.rglob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if sum(1 for _ in ast.walk(node)) < 25:
                continue
            normalized = ast.dump(
                ast.Module(body=node.body, type_ignores=[]),
                include_attributes=False,
            )
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            function_bodies[digest].append((path, node.name, node.lineno))
    for matches in function_bodies.values():
        if len({path for path, _, _ in matches}) < 2:
            continue
        rendered = ", ".join(
            f"{path.relative_to(ROOT)}:{line}:{name}"
            for path, name, line in matches
        )
        errors.append(f"duplicate non-trivial function implementation: {rendered}")

    runtime_modules: dict[str, Path] = {}
    file_modules: dict[Path, tuple[str, bool]] = {}
    for path in sorted(RUNTIME.rglob("*.py")):
        parts = list(path.with_suffix("").relative_to(ROOT).parts)
        is_initializer = parts[-1] == "__init__"
        if is_initializer:
            parts = parts[:-1]
        module_name = ".".join(parts)
        runtime_modules[module_name] = path
        file_modules[path] = (module_name, is_initializer)

    incoming: dict[str, set[str]] = defaultdict(set)
    import_sources = [
        *ROOT.joinpath("runtime").rglob("*.py"),
        *ROOT.joinpath("tests").rglob("*.py"),
        *ROOT.joinpath("build").rglob("*.py"),
        *(
            ROOT / name
            for name in (
                "main.py",
                "__main__.py",
                "cli.py",
                "runtime_health.py",
                "runtime_notification_health.py",
                "runtime_requirements.py",
            )
        ),
    ]
    for source_path in import_sources:
        if not source_path.is_file():
            continue
        source_tree = ast.parse(
            source_path.read_text(encoding="utf-8-sig"),
            filename=str(source_path),
        )
        source_module, is_initializer = file_modules.get(source_path, ("", False))
        source_package = (
            source_module if is_initializer else source_module.rpartition(".")[0]
        )
        for node in ast.walk(source_tree):
            candidates: list[str] = []
            if isinstance(node, ast.Import):
                candidates.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package_parts = source_package.split(".") if source_package else []
                    base_parts = package_parts[: max(0, len(package_parts) - node.level + 1)]
                    if node.module:
                        base_parts.extend(node.module.split("."))
                    base = ".".join(base_parts)
                else:
                    base = node.module or ""
                if base:
                    candidates.append(base)
                candidates.extend(
                    ".".join(part for part in (base, alias.name) if part)
                    for alias in node.names
                    if alias.name != "*"
                )
            for candidate in candidates:
                parts = candidate.split(".")
                for index in range(len(parts), 0, -1):
                    imported_module = ".".join(parts[:index])
                    if imported_module in runtime_modules:
                        incoming[imported_module].add(str(source_path.relative_to(ROOT)))
                        break

    for module_name, path in sorted(runtime_modules.items()):
        if path.name == "__init__.py":
            continue
        if not incoming[module_name]:
            errors.append(
                "runtime module has no incoming import: "
                f"{path.relative_to(ROOT)}"
            )

    single_instance = RUNTIME / "bootstrap" / "runtime" / "single_instance.py"
    if single_instance.is_file():
        tree = ast.parse(single_instance.read_text(encoding="utf-8"))
        names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        missing = sorted(REQUIRED_SINGLE_INSTANCE_API - names)
        if missing:
            errors.append(f"single-instance bootstrap API is incomplete: {missing}")

    translations = RUNTIME / "application" / "services" / "translations.py"
    if translations.is_file():
        source = translations.read_text(encoding="utf-8")
        if 'parents[2] / "resources"' not in source:
            errors.append("translation resource root is not runtime/resources")

    migration = RUNTIME / "shared" / "settings" / "runtime_migration.py"
    if migration.is_file():
        source = migration.read_text(encoding="utf-8")
        if 'CANONICAL_SETTINGS_FILENAME = "settings.ini"' not in source:
            errors.append("canonical settings filename is not settings.ini")

    if errors:
        raise RuntimeError("HERFY_STRUCTURE_CONTRACT_FAILED\n - " + "\n - ".join(errors))

    init_count = sum(1 for _ in RUNTIME.rglob("__init__.py"))
    python_count = sum(1 for _ in RUNTIME.rglob("*.py"))
    print(
        "HERFY_STRUCTURE_CONTRACT_OK "
        f"python_files={python_count} package_initializers={init_count} "
        f"max_init_bytes={MAX_INIT_BYTES}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
