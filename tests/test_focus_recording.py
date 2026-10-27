from types import SimpleNamespace

from study_lock.timer import FocusStage, TimerState
from study_lock.ui import FocusTimerPanel


def test_timer_records_monotonic_elapsed_time_and_excludes_paused_time(monkeypatch):
    panel = FocusTimerPanel.__new__(FocusTimerPanel)
    panel.state = TimerState(0, 60, True)
    panel.stages = [FocusStage("Read", 60)]
    panel._last_focus_tick = 100.0
    recorded = []
    panel.on_focus_seconds = recorded.append
    panel.status_var = SimpleNamespace(set=lambda _value: None)
    panel._cancel_tick = lambda: None
    panel._refresh = lambda: None
    monkeypatch.setattr("study_lock.ui.time.monotonic", lambda: 101.5)
    panel._pause()
    assert recorded == [1.5]
    monkeypatch.setattr("study_lock.ui.time.monotonic", lambda: 180.0)
    panel._pause()
    assert recorded == [1.5]


def test_focus_recording_caps_elapsed_time_and_surfaces_save_errors(monkeypatch):
    panel = FocusTimerPanel.__new__(FocusTimerPanel)
    panel.state = TimerState(0, 2, True)
    panel.stages = [FocusStage("Read", 60)]
    panel._last_focus_tick = 100.0
    recorded = []
    panel.on_focus_seconds = recorded.append
    monkeypatch.setattr("study_lock.ui.time.monotonic", lambda: 160.0)
    panel._record_elapsed()
    assert recorded == [2]
    messages = []
    panel.status_var = SimpleNamespace(set=messages.append)
    panel.on_focus_seconds = lambda _seconds: (_ for _ in ()).throw(OSError("disk error"))
    monkeypatch.setattr("study_lock.ui.time.monotonic", lambda: 161.0)
    panel._record_elapsed()
    assert messages and "disk error" in messages[-1]


def test_reopening_timer_reuses_existing_window_instead_of_double_counting(monkeypatch, tmp_path):
    from datetime import date
    from study_lock.progress import DailyProgress
    from study_lock.ui import StudyPanel
    panel = StudyPanel.__new__(StudyPanel)
    panel.current_date = date(2026, 7, 28)
    panel.root, panel.plan, panel.workspace_root = object(), object(), tmp_path
    panel.daily_progress = DailyProgress(panel.current_date)
    created, focused = [], []
    def factory(*_args, **_kwargs):
        timer = SimpleNamespace(window=SimpleNamespace(winfo_exists=lambda: True, deiconify=lambda: focused.append("show"), lift=lambda: focused.append("lift"), focus_set=lambda: focused.append("focus")))
        created.append(timer)
        return timer
    monkeypatch.setattr("study_lock.ui.FocusTimerPanel", factory)
    panel._open_focus_timer()
    panel._open_focus_timer()
    assert len(created) == 1
    assert focused == ["show", "lift", "focus"]
