from __future__ import annotations
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from runtime.shared.errors import FILESYSTEM_OPERATION_EXCEPTIONS, PARSE_OPERATION_EXCEPTIONS

logger = logging.getLogger(__name__)


def read_json_dict(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except FILESYSTEM_OPERATION_EXCEPTIONS:
        logger.exception("Failed to read JSON dictionary: %s", file_path)
        return {}
    except PARSE_OPERATION_EXCEPTIONS:
        logger.exception("Failed to parse JSON dictionary: %s", file_path)
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def write_bytes_atomic(path: str | Path, payload: bytes) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{file_path.name}.",
            suffix=".tmp",
            dir=file_path.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(file_path)
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except FILESYSTEM_OPERATION_EXCEPTIONS:
                logger.debug(
                    "Temporary atomic-write cleanup failed: %s",
                    temp_path,
                    exc_info=True,
                )


def write_json_dict(
    path: str | Path, payload: dict[str, Any], *, ensure_ascii: bool = False
) -> None:
    encoded = json.dumps(
        dict(payload or {}), ensure_ascii=ensure_ascii, indent=2
    ).encode("utf-8")
    write_bytes_atomic(path, encoded)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
