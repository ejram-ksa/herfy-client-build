from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_gui_bootstrap_has_no_duplicate_window_reveal_or_global_update_timer():
    source = _text("runtime/bootstrap/runtime/app_bootstrap.py")
    run_gui = source[source.index("def run_gui_application"):]
    assert run_gui.count("_show_startup_window(window)") == 1
    assert "QTimer.singleShot(250" not in run_gui
    assert "QTimer.singleShot(1200" not in run_gui
    assert "QTimer.singleShot(18000" not in run_gui
    assert "target=_background_sync_remote_ui" in run_gui
    assert 'name="herfy-remote-ui-sync"' in run_gui


def test_login_followups_are_event_driven_not_delayed_by_seconds():
    source = _text("runtime/presentation/main_window/cloud_sections/cloud_runtime.py")
    section = source[source.index("def _schedule_login_followups"):]
    section = section[: section.index("def _apply_logged_in_shell_state")]
    assert "QTimer.singleShot(0, self._initial_cloud_hydrate_async)" in section
    assert "3600" not in section


def test_update_checks_are_queued_without_fixed_startup_sleep():
    source = _text("runtime/presentation/main_window/session_sections/session.py")
    section = source[source.index("def _apply_runtime_update_flow"):]
    section = section[: section.index("def _handle_startup_contract")]
    assert section.count("QTimer.singleShot(0, self._maybe_check_updates)") == 2
    assert "QTimer.singleShot(1200" not in section
    assert "QTimer.singleShot(optional_delay_ms" not in section

def test_login_hydration_orders_usage_sync_by_completion_not_fixed_delay():
    source = _text("runtime/presentation/main_window/cloud_sections/cloud_runtime.py")

    hydrate = source[source.index("def _hydrate_login_state"):]
    hydrate = hydrate[: hydrate.index("def _prefetch_allowed_branches_async")]
    assert "_schedule_usage_sync" not in hydrate
    assert "2400" not in hydrate

    finished = source[source.index("def _on_initial_cloud_hydrate_finished"):]
    finished = finished[: finished.index("class CloudStatusControllerMixin")]
    assert "self._login_hydrate_pending = False" in finished
    assert "self._schedule_usage_sync(" in finished
    assert "force_refresh=True" in finished
    assert "include_pending=True" in finished
    assert "delay_ms=0" in finished

    login = source[source.index("def on_login_success"):]
    login = login[: login.index("def _hydrate_login_state")]
    assert "QTimer.singleShot(0, lambda: self.check_expiry(allow_network=False))" in login
    assert "QTimer.singleShot(300" not in login

