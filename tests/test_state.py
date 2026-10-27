from datetime import date
from pathlib import Path

from study_lock.state import LockState, RuntimeState, append_event, load_state, save_state


def test_runtime_state_round_trips_as_json(tmp_path: Path):
    state_path = tmp_path / "runtime/state.json"
    original = RuntimeState(date(2026, 7, 28), LockState.LOCKED, "daily/2026-07-28.md")

    save_state(state_path, original)
    restored = load_state(state_path)

    assert restored == original


def test_missing_state_defaults_to_safe_config(tmp_path: Path):
    state = load_state(tmp_path / "missing.json", default_date=date(2026, 7, 28))

    assert state.status is LockState.SAFE_CONFIG
    assert state.current_date == date(2026, 7, 28)


def test_append_event_writes_one_json_object_per_line(tmp_path: Path):
    events_path = tmp_path / "runtime/events.jsonl"

    append_event(events_path, "locked", {"plan": "2026-07-28.md"})

    assert events_path.read_text(encoding="utf-8").count("\n") == 1
    assert '"event": "locked"' in events_path.read_text(encoding="utf-8")
def test_state_save_uses_atomic_replace(monkeypatch, tmp_path):
    from pathlib import Path
    from datetime import date
    from study_lock.state import RuntimeState, LockState, save_state
    path = tmp_path / "state.json"
    save_state(path, RuntimeState(date(2026, 7, 28), LockState.LOCKED))
    previous = path.read_bytes()
    def fail(*_args):
        raise OSError("replace unavailable")
    monkeypatch.setattr(Path, "replace", fail)
    import pytest
    with pytest.raises(OSError, match="replace"):
        save_state(path, RuntimeState(date(2026, 7, 28), LockState.UNLOCKED))
    assert path.read_bytes() == previous
    assert len(list(tmp_path.iterdir())) == 1
