from types import SimpleNamespace

import pytest

from study_lock.recovery import RecoveryGate
from study_lock.ui import StudyPanel


def panel_without_gui():
    panel = StudyPanel.__new__(StudyPanel)
    panel.recovery_gate = RecoveryGate(100.0)
    panel.messages = []
    panel.callbacks = []
    panel.status_var = SimpleNamespace(set=panel.messages.append)
    panel.root = SimpleNamespace(after=lambda *args: panel.callbacks.append(args), destroy=lambda: None)
    panel.on_recovery = lambda *_args: SimpleNamespace(status=SimpleNamespace(value="RECOVERY"))
    return panel


def test_fractional_countdown_does_not_open_confirmation_early(monkeypatch):
    panel = panel_without_gui()
    dialogs = []
    monkeypatch.setattr("study_lock.ui.time.monotonic", lambda: 159.5)
    monkeypatch.setattr("study_lock.ui.simpledialog.askstring", lambda *_args, **_kwargs: dialogs.append(True))
    panel._recovery_tick()
    assert dialogs == []
    assert "1 秒" in panel.messages[-1]
    assert panel.callbacks


@pytest.mark.parametrize("phrase", [None, "wrong"])
def test_cancel_or_wrong_phrase_allows_a_new_recovery_request(monkeypatch, phrase):
    panel = panel_without_gui()
    monkeypatch.setattr("study_lock.ui.time.monotonic", lambda: 160.0)
    monkeypatch.setattr("study_lock.ui.simpledialog.askstring", lambda *_args, **_kwargs: phrase)
    monkeypatch.setattr("study_lock.ui.messagebox.showwarning", lambda *_args, **_kwargs: None)
    panel.on_recovery = lambda value, gate: gate.confirm(value, now=160.0)
    panel._recovery_tick()
    assert panel.recovery_gate is None
    panel._request_recovery()
    assert panel.recovery_gate.started_at == 160.0


def test_recovery_io_error_is_visible_and_retryable(monkeypatch):
    panel = panel_without_gui()
    warnings = []
    monkeypatch.setattr("study_lock.ui.time.monotonic", lambda: 160.0)
    monkeypatch.setattr("study_lock.ui.simpledialog.askstring", lambda *_args, **_kwargs: "I ACCEPT RECOVERY")
    monkeypatch.setattr("study_lock.ui.messagebox.showwarning", lambda *args, **_kwargs: warnings.append(args))
    def fail(*_args):
        raise OSError("disk unavailable")
    panel.on_recovery = fail
    panel._recovery_tick()
    assert panel.recovery_gate is None
    assert warnings and "disk unavailable" in warnings[0][1]


def test_background_health_failure_is_shown_and_releases_window_close_guard(monkeypatch):
    panel = panel_without_gui()
    panel.health_provider = lambda: "guard unavailable"
    panel.enforce_close_guard = True
    panel._health_job = "scheduled"
    warnings = []
    monkeypatch.setattr("study_lock.ui.messagebox.showwarning", lambda *args, **_kwargs: warnings.append(args))
    panel._check_health()
    assert not panel.enforce_close_guard
    assert "SAFE_CONFIG" in panel.messages[-1]
    assert warnings
    assert panel._health_job is None
