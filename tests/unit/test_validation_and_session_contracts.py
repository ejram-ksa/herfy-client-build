from pathlib import Path

from runtime.services.session import SessionStore


def test_session_store_invalid_saved_at_falls_back_to_zero():
    assert SessionStore._safe_int("invalid") == 0
    assert SessionStore._safe_int(-3) == 0


def test_release_verifiers_use_canonical_build_paths():
    root = Path(__file__).resolve().parents[2]
    canonical = (root / "build/release/verify_canonical_paths_and_update.py").read_text(encoding="utf-8")
    notification = (root / "build/release/verify_notification_runtime_contract.py").read_text(encoding="utf-8")
    update = (root / "build/release/verify_update_install_contract.py").read_text(encoding="utf-8")
    assert "build/installer/HerfyClient_Custom_Installer.iss" in canonical
    assert '"build" / "installer" / "pyinstaller"' in notification
    assert "from runtime.bootstrap.runtime.update_agent import" in update


def test_production_restore_uses_canonical_policy_and_no_temporary_api_client():
    root = Path(__file__).resolve().parents[2]
    source = (root / "runtime/presentation/main_window/session_sections/session.py").read_text(encoding="utf-8")
    assert "classify_restore_failure" in source
    assert "decision.clear_persistent_session" in source
    assert "service.pull_now()" not in source
    assert "session_identity_mismatch" in source
