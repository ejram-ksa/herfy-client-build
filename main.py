from __future__ import annotations
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True


def _prepare_source_runtime() -> None:
    source_root = Path(__file__).resolve().parent
    root_text = str(source_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    if not getattr(sys, "frozen", False):
        try:
            os.chdir(source_root)
        except OSError as exc:
            try:
                sys.stderr.write(f"Unable to use application folder as cwd: {exc}\n")
            except OSError:
                return


_prepare_source_runtime()


def _dependencies_ready() -> bool:
    from runtime_requirements import (
        format_missing_requirements_message,
        missing_runtime_requirements,
    )

    missing = missing_runtime_requirements()
    if not missing:
        return True
    message = format_missing_requirements_message(missing)
    try:
        sys.stderr.write(message)
    except OSError:
        return False
    try:
        from runtime.shared.settings.logging_setup import setup_crash_logging

        setup_crash_logging()
        logger = __import__("logging").getLogger(__name__)
        logger.error(message.rstrip())
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return False


def main() -> int:
    from cli import handle_cli_shortcut

    cli_result = handle_cli_shortcut(sys.argv[1:])
    if cli_result is not None:
        return cli_result
    if not _dependencies_ready():
        return 2
    from runtime.bootstrap.runtime.app_bootstrap import run

    return run(sys.argv[1:])


def _run_entrypoint() -> int:
    try:
        return main()
    except (
        AttributeError,
        ImportError,
        ModuleNotFoundError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        try:
            from runtime.shared.settings.logging_setup import (
                install_exception_hooks,
                setup_crash_logging,
            )

            setup_crash_logging()
            install_exception_hooks()
            sys.excepthook(*sys.exc_info())
        finally:
            raise SystemExit(1) from exc


if __name__ == "__main__":
    raise SystemExit(_run_entrypoint())
