from __future__ import annotations

import json
from pathlib import Path

from runtime.infrastructure.persistence import secure_store


def test_plaintext_session_snapshot_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text(
        json.dumps({"refresh_token": "must-not-be-read"}), encoding="utf-8"
    )
    assert secure_store.read_secure_json(path) == {}


def test_secure_session_snapshot_round_trip_uses_envelope(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    expected = {"refresh_token": "secret", "user_id": "1019"}
    secure_store.write_secure_json(path, expected)

    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["format"] == "secure-json-v1"
    assert envelope["method"] in {"dpapi", "local-v1"}
    assert "secret" not in path.read_text(encoding="utf-8")
    assert secure_store.read_secure_json(path) == expected


def test_dpapi_noninteractive_flag_is_enabled() -> None:
    source = Path(secure_store.__file__).read_text(encoding="utf-8")
    assert secure_store._CRYPTPROTECT_UI_FORBIDDEN == 0x1
    assert "_CRYPTPROTECT_UI_FORBIDDEN," in source
