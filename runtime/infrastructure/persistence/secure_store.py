from __future__ import annotations
import base64
import ctypes
import hashlib
import hmac
import json
import logging
import os
import platform
import tempfile
from pathlib import Path
from typing import Any
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS

logger = logging.getLogger(__name__)
_TRUE_VALUES = {"1", "true", "yes", "on"}
_PURPOSE = b"HerfyClient.session.v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _windows_dpapi(raw: bytes, *, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_pointer = ctypes.POINTER(_DATA_BLOB)
    for operation in (crypt32.CryptProtectData, crypt32.CryptUnprotectData):
        operation.argtypes = [
            blob_pointer,
            ctypes.c_void_p,
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            blob_pointer,
        ]
        operation.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    # Keep the backing buffers alive until the native DPAPI call returns.
    # A cast pointer alone does not retain the temporary ctypes buffer.
    input_buffer = ctypes.create_string_buffer(raw)
    entropy_buffer = ctypes.create_string_buffer(_PURPOSE)
    in_blob = _DATA_BLOB(
        len(raw),
        ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    out_blob = _DATA_BLOB()
    entropy = _DATA_BLOB(
        len(_PURPOSE),
        ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    operation_name = "CryptProtectData" if protect else "CryptUnprotectData"
    if not operation(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    ):
        raise OSError(f"{operation_name} failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _windows_protect(raw: bytes) -> bytes:
    return _windows_dpapi(raw, protect=True)


def _windows_unprotect(raw: bytes) -> bytes:
    return _windows_dpapi(raw, protect=False)


def _machine_key() -> bytes:
    material = "|".join(
        [
            platform.node(),
            platform.system(),
            platform.machine(),
            (
                str(os.getuid())
                if hasattr(os, "getuid")
                else os.environ.get("USERNAME", "")
            ),
        ]
    ).encode("utf-8", "ignore")
    return hashlib.pbkdf2_hmac("sha256", material, _PURPOSE, 120000, dklen=32)


def _xor_stream(data: bytes, key: bytes) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hmac.new(
            key, _PURPOSE + counter.to_bytes(8, "big"), hashlib.sha256
        ).digest()
        out.extend(block)
        counter += 1
    return bytes((a ^ b for a, b in zip(data, out, strict=False)))


def _fallback_protect(raw: bytes) -> bytes:
    key = _machine_key()
    ciphertext = _xor_stream(raw, key)
    tag = hmac.new(key, _PURPOSE + ciphertext, hashlib.sha256).digest()
    return tag + ciphertext


def _fallback_unprotect(raw: bytes) -> bytes:
    if len(raw) < 32:
        raise ValueError("secure payload is too short")
    key = _machine_key()
    tag, ciphertext = (raw[:32], raw[32:])
    expected = hmac.new(key, _PURPOSE + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("secure payload integrity check failed")
    return _xor_stream(ciphertext, key)


def _allow_insecure_local_session_store() -> bool:
    value = os.getenv("PTS_ALLOW_INSECURE_LOCAL_SESSION_STORE", "")
    return str(value or "").strip().lower() in _TRUE_VALUES


def _protect(raw: bytes) -> tuple[str, bytes]:
    if os.name == "nt":
        try:
            return ("dpapi", _windows_protect(raw))
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if not _allow_insecure_local_session_store():
                logger.exception(
                    "Windows DPAPI session protection failed; session token was not saved"
                )
                raise RuntimeError("Windows DPAPI session protection failed") from exc
            logger.warning(
                "Windows session protection failed; using explicitly enabled local fallback",
                exc_info=True,
            )
    return ("local-v1", _fallback_protect(raw))


def _unprotect(method: str, raw: bytes) -> bytes:
    if method == "dpapi":
        return _windows_unprotect(raw)
    if method == "local-v1":
        return _fallback_unprotect(raw)
    raise ValueError(f"unsupported secure payload method: {method}")


def read_secure_json(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        if payload.get("format") != "secure-json-v1":
            logger.warning(
                "Rejected plaintext or unsupported secure session snapshot: %s",
                file_path,
            )
            return {}
        method = str(payload.get("method") or "")
        encoded = str(payload.get("payload") or "")
        if not encoded:
            return {}
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
        plain = _unprotect(method, raw)
        data = json.loads(plain.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        logger.warning("Secure session snapshot could not be read: %s", file_path)
        return {}


def write_secure_json(
    path: str | Path, data: dict[str, Any], *, ensure_ascii: bool = False
) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=ensure_ascii, separators=(",", ":")).encode(
        "utf-8"
    )
    method, protected = _protect(raw)
    payload = {
        "format": "secure-json-v1",
        "method": method,
        "payload": base64.b64encode(protected).decode("ascii"),
    }
    encoded_payload = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
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
            handle.write(encoded_payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "Unable to restrict secure file permissions for %s",
                temp_path,
                exc_info=True,
            )
        temp_path.replace(file_path)
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug(
                    "Temporary secure-file cleanup failed: %s",
                    temp_path,
                    exc_info=True,
                )
