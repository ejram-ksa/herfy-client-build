from __future__ import annotations
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeAlias
import faulthandler
import logging
import os
import sys
import tempfile
import threading
import traceback
from runtime.shared.settings.config import APP_DISPLAY_NAME, APP_RUNTIME_DIR_NAME, app_root_dir
from runtime.shared.errors import FILESYSTEM_OPERATION_EXCEPTIONS
from runtime.shared.settings.version import __version__ as APP_VERSION

ExceptionClasses: TypeAlias = type[BaseException] | tuple[type[BaseException], ...]


def _normalize_log_path(path: str | os.PathLike[str] | None) -> str | None:
    if path in (None, ""):
        return None
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(path)


def _handler_file_path(handler: logging.Handler) -> str | None:
    filename = getattr(handler, "baseFilename", None)
    return _normalize_log_path(filename) if filename else None


def _has_file_handler(root_logger: logging.Logger, path: str) -> bool:
    normalized = _normalize_log_path(path)
    return any(
        (_handler_file_path(handler) == normalized for handler in root_logger.handlers)
    )


def _ensure_parent_dir(path: str, file_exceptions: ExceptionClasses) -> None:
    parent = os.path.dirname(path)
    if not parent:
        return
    os.makedirs(parent, exist_ok=True)


def _make_formatter(log_format: str) -> logging.Formatter:
    return logging.Formatter(log_format)


def _add_file_handler(
    root_logger: logging.Logger,
    log_file: str,
    *,
    level: int,
    formatter: logging.Formatter,
    file_exceptions: ExceptionClasses,
) -> bool:
    normalized = _normalize_log_path(log_file)
    if not normalized or _has_file_handler(root_logger, normalized):
        return False
    try:
        _ensure_parent_dir(normalized, file_exceptions)
        handler = logging.FileHandler(normalized, encoding="utf-8")
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        return True
    except file_exceptions:
        return False


def _add_stream_handler(
    root_logger: logging.Logger, *, level: int, formatter: logging.Formatter
) -> None:
    if any(
        (isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers)
    ):
        return
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


def configure_root_logging(
    log_file: str | None = None,
    *,
    level: int = logging.INFO,
    log_format: str = "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    fallback_level: int | None = None,
    file_exceptions: ExceptionClasses = OSError,
    additional_files: Iterable[str] | None = None,
) -> None:
    root_logger = logging.getLogger()
    effective_level = level
    if root_logger.handlers and root_logger.level not in (logging.NOTSET, 0):
        effective_level = min(root_logger.level, level)
    root_logger.setLevel(effective_level)
    formatter = _make_formatter(log_format)
    attached_file = False
    requested_files = []
    if log_file:
        requested_files.append(str(log_file))
    if additional_files:
        requested_files.extend((str(path) for path in additional_files if path))
    for requested in dict.fromkeys(requested_files):
        attached_file = (
            _add_file_handler(
                root_logger,
                requested,
                level=level,
                formatter=formatter,
                file_exceptions=file_exceptions,
            )
            or attached_file
        )
    if not root_logger.handlers or (not attached_file and requested_files):
        _add_stream_handler(
            root_logger,
            level=fallback_level if fallback_level is not None else level,
            formatter=formatter,
        )


def flush_root_logging() -> None:
    for handler in list(logging.getLogger().handlers):
        try:
            handler.flush()
        except (OSError, RuntimeError, ValueError):
            continue


ErrorPresenter = Callable[[str, str], None]
_error_presenter: ErrorPresenter | None = None
_crash_stream: Any | None = None


def candidate_log_dirs() -> list[str]:
    try:
        primary = str((app_root_dir() / "logs").resolve())
    except FILESYSTEM_OPERATION_EXCEPTIONS:
        if sys.platform.startswith("win"):
            base = os.environ.get("APPDATA") or os.path.join(
                os.path.expanduser("~"), "AppData", "Roaming"
            )
            primary = os.path.join(base, APP_RUNTIME_DIR_NAME, "logs")
        else:
            primary = os.path.join(
                os.path.expanduser("~"), ".config", APP_RUNTIME_DIR_NAME, "logs"
            )
    fallback = str(
        (Path(tempfile.gettempdir()) / APP_RUNTIME_DIR_NAME / "logs").resolve()
    )
    return list(dict.fromkeys([primary, fallback]))


def ensure_log_dir() -> str:
    for log_dir in candidate_log_dirs():
        try:
            os.makedirs(log_dir, exist_ok=True)
            probe = Path(log_dir) / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return log_dir
        except FILESYSTEM_OPERATION_EXCEPTIONS:
            continue
    raise OSError("No writable log directory is available")


def setup_crash_logging() -> None:
    global _crash_stream
    log_dir = ensure_log_dir()
    configure_root_logging(
        os.path.join(log_dir, "desktop.log"),
        level=logging.INFO,
        file_exceptions=FILESYSTEM_OPERATION_EXCEPTIONS,
    )
    try:
        if _crash_stream is None or getattr(_crash_stream, "closed", True):
            _crash_stream = open(
                os.path.join(log_dir, "crash.log"),
                "a",
                encoding="utf-8",
                errors="ignore",
            )
        faulthandler.enable(file=_crash_stream, all_threads=True)
    except FILESYSTEM_OPERATION_EXCEPTIONS:
        try:
            faulthandler.enable(all_threads=True)
        except RuntimeError:
            logging.debug("Crash logger fallback enable failed", exc_info=True)
    logging.info("Crash logging initialized. log_dir=%s", log_dir)


def _crash_report_header() -> str:
    return "\n".join(
        (
            "=" * 78,
            f"timestamp={datetime.now().isoformat(timespec='seconds')}",
            f"app={APP_DISPLAY_NAME}",
            f"version={APP_VERSION}",
            f"python={sys.version}",
            f"executable={sys.executable}",
            f"argv={sys.argv!r}",
            f"cwd={os.getcwd()}",
            "=" * 78,
        )
    )


def write_emergency_crash_report(message: str) -> list[str]:
    payload = f"{_crash_report_header()}\n{message}\n"
    written: list[str] = []
    for log_dir in candidate_log_dirs():
        try:
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, "fatal_error.log")
            with open(path, "a", encoding="utf-8", errors="ignore") as handle:
                handle.write(payload)
                handle.write("\n")
            written.append(path)
            break
        except FILESYSTEM_OPERATION_EXCEPTIONS:
            continue
    flush_root_logging()
    return written


def _log_file_hint() -> str:
    preferred = []
    for log_dir in candidate_log_dirs():
        preferred.extend(
            [
                os.path.join(log_dir, "desktop.log"),
                os.path.join(log_dir, "fatal_error.log"),
            ]
        )
    return "\n".join((f"- {path}" for path in dict.fromkeys(preferred)))


def install_exception_hooks(error_presenter: ErrorPresenter | None = None) -> None:
    global _error_presenter
    if error_presenter is not None:
        _error_presenter = error_presenter

    def excepthook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        message = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.critical("Unhandled exception:\n%s", message)
        written = write_emergency_crash_report(message)
        hint = "\n".join((f"- {path}" for path in written)) or _log_file_hint()
        if _error_presenter is not None:
            _error_presenter(
                f"Unexpected error - {APP_DISPLAY_NAME}",
                f"The application encountered an unexpected error.\n\nA crash report was written here:\n{hint}",
            )

    sys.excepthook = excepthook

    def thread_excepthook(args: threading.ExceptHookArgs) -> None:
        message = "".join(
            traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback
            )
        )
        logging.critical(
            "Unhandled thread exception (thread=%s):\n%s",
            getattr(args, "thread", None),
            message,
        )
        write_emergency_crash_report(message)

    threading.excepthook = thread_excepthook
