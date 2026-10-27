from datetime import date
from pathlib import Path

from study_lock.process_guard import GuardResult
from study_lock.runtime import StudyLockSession, should_log_guard_event
from study_lock.state import LockState
from study_lock.ui import add_temporary_app, add_temporary_domain
import pytest
import threading


@pytest.fixture(autouse=True)
def fake_browser_discovery(monkeypatch):
    monkeypatch.setattr("study_lock.runtime.wait_for_owned_processes", lambda roots, *_args, **_kwargs: {pid: 10.0 for pid in roots}, raising=False)


SOURCE_PLAN = Path(__file__).resolve().parents[1] / "examples/demo-workspace" / "study-plans/daily/2026-07-28.md"


def copy_workspace_plan(tmp_path: Path) -> Path:
    plan = tmp_path / "2026-07-28.md"
    plan.write_text(SOURCE_PLAN.read_text(encoding="utf-8"), encoding="utf-8")
    return plan


def test_simulation_session_starts_proxy_and_stops_cleanly(tmp_path: Path):
    plan = copy_workspace_plan(tmp_path)

    session = StudyLockSession(tmp_path, plan, today=date(2026, 7, 28), simulation=True)
    state = session.start()

    assert state.status is LockState.LOCKED
    assert session.proxy is not None
    assert session.proxy.proxy_port > 0
    assert session.guard_thread is not None

    session.stop()

    assert session.proxy is None
    assert session.guard_thread is None


def test_enforce_session_launches_and_closes_controlled_browser(tmp_path: Path):
    plan = copy_workspace_plan(tmp_path)
    calls: list[tuple[str, object]] = []

    class FakeBrowser:
        pid = 9001

    def fake_close() -> None:
        calls.append(("close", None))

    def fake_stop(root_pids, profile_dir, owned_pids) -> None:
        calls.append(("stop", (set(root_pids), profile_dir, set(owned_pids))))

    def fake_launch(executable, profile_dir, *, proxy_port, url=None):
        calls.append(("launch", (executable, profile_dir, proxy_port, url)))
        return FakeBrowser()

    session = StudyLockSession(
        tmp_path,
        plan,
        today=date(2026, 7, 28),
        simulation=False,
        chrome_finder=lambda: Path("chrome.exe"),
        ordinary_chrome_closer=fake_close,
        browser_launcher=fake_launch,
        browser_stopper=fake_stop,
    )

    state = session.start()
    session.stop()

    assert state.status is LockState.LOCKED
    assert calls[0] == ("close", None)
    assert calls[1][0] == "launch"
    assert calls[1][1][2] > 0
    assert calls[2][0] == "stop"
    assert calls[2][1][0] == {9001}


def test_guard_event_is_logged_once_per_process_name_and_action():
    seen: set[tuple[str, str]] = set()
    result = GuardResult("notepad.exe", "blocked", "unlisted user process terminated")

    assert should_log_guard_event(seen, result) is True
    assert should_log_guard_event(seen, result) is False


def test_session_refreshes_temporary_allowlist_overrides(tmp_path: Path):
    plan = copy_workspace_plan(tmp_path)
    session = StudyLockSession(tmp_path, plan, today=date(2026, 7, 28), simulation=True)
    session.start()

    add_temporary_app(tmp_path / "study-lock/runtime", date(2026, 7, 28), "newtool.exe")
    add_temporary_domain(tmp_path / "study-lock/runtime", date(2026, 7, 28), "example.com")
    session.refresh_overrides()

    assert session.guard is not None
    assert "newtool.exe" in session.guard.allowed_apps
    assert session.proxy is not None
    assert "example.com" in session.proxy.policy.allowed_domains
    session.stop()


def test_session_adds_resource_domains_to_the_proxy_allowlist(tmp_path: Path):
    plan = copy_workspace_plan(tmp_path)
    session = StudyLockSession(tmp_path, plan, today=date(2026, 7, 28), simulation=True)

    session.start()

    assert session.proxy is not None
    assert "bilibili.com" in session.proxy.policy.allowed_domains
    assert "docs.opencv.org" in session.proxy.policy.allowed_domains
    session.stop()


def test_session_opens_urls_with_the_controlled_browser(tmp_path: Path):
    plan = copy_workspace_plan(tmp_path)
    calls: list[tuple[object, object]] = []

    class FakeBrowser:
        pid = 9002

    def fake_launch(executable, profile_dir, *, proxy_port, url=None):
        calls.append((profile_dir, url))
        return FakeBrowser()

    session = StudyLockSession(
        tmp_path,
        plan,
        today=date(2026, 7, 28),
        simulation=False,
        chrome_finder=lambda: Path("chrome.exe"),
        ordinary_chrome_closer=lambda: None,
        browser_launcher=fake_launch,
        browser_stopper=lambda *_args: None,
    )
    session.start()

    session.open_url("https://example.com/video")

    assert calls[-1][1] == "https://example.com/video"
    session.stop()


def test_session_opens_local_files_with_the_controlled_browser(tmp_path: Path):
    plan = copy_workspace_plan(tmp_path)
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"pdf")
    calls: list[tuple[object, object]] = []

    class FakeBrowser:
        pid = 9003

    def fake_launch(executable, profile_dir, *, proxy_port, url=None):
        calls.append((profile_dir, url))
        return FakeBrowser()

    session = StudyLockSession(
        tmp_path,
        plan,
        today=date(2026, 7, 28),
        simulation=False,
        chrome_finder=lambda: Path("chrome.exe"),
        ordinary_chrome_closer=lambda: None,
        browser_launcher=fake_launch,
        browser_stopper=lambda *_args: None,
    )
    session.start()

    session.open_file(paper)

    assert calls[-1][1] == paper.resolve().as_uri()
    session.stop()


def test_guard_loop_inspects_processes_without_referencing_missing_callback(tmp_path: Path):
    session = StudyLockSession(tmp_path, tmp_path / "plan.md", simulation=True)
    calls = []

    class OneIterationStopEvent:
        def wait(self, _timeout):
            calls.append("wait")
            return len(calls) > 1

    class RecordingGuard:
        def inspect_all(self):
            calls.append("inspect")
            return []

    session.stop_event = OneIterationStopEvent()
    session.guard = RecordingGuard()

    session._guard_loop()

    assert calls == ["wait", "inspect", "wait"]


def test_guard_failure_moves_to_safe_config_and_cleans_up(tmp_path: Path):
    session = StudyLockSession(tmp_path, tmp_path / "plan.md")
    session.controller._set_state(LockState.LOCKED)
    class FailedGuard:
        def inspect_all(self):
            raise RuntimeError("guard unavailable")
    class ImmediateEvent:
        def wait(self, _timeout):
            return False
        def set(self):
            pass
    session.stop_event = ImmediateEvent()
    session.guard = FailedGuard()
    session.guard_thread = threading.current_thread()
    session._guard_loop()
    assert session.controller.state.status is LockState.SAFE_CONFIG
    assert session.guard is None
    assert session.health_error == "guard unavailable"
    assert "guard_failed" in session.events_path.read_text(encoding="utf-8")


def test_stop_is_idempotent_even_when_cleanup_raises(tmp_path: Path):
    session = StudyLockSession(tmp_path, tmp_path / "plan.md")
    calls = []
    class BadProxy:
        def shutdown(self):
            calls.append("shutdown")
            raise OSError("already closed")
        def server_close(self):
            calls.append("close")
    session.proxy = BadProxy()
    session.stop()
    session.stop()
    assert calls == ["shutdown", "close"]
    assert session.proxy is None


def test_owned_processes_are_replaced_instead_of_kept_forever(monkeypatch, tmp_path: Path):
    session = StudyLockSession(tmp_path, tmp_path / "plan.md")
    session.browser_root_pids = {42}
    session.owned_browser_pids.add(42)
    session.browser_identities = {42: 10.0}
    monkeypatch.setattr("study_lock.runtime.collect_owned_processes", lambda *_args, **_kwargs: {}, raising=False)
    class OneIteration:
        n = 0
        def wait(self, _timeout):
            self.n += 1
            return self.n > 1
    class Guard:
        def inspect_all(self):
            assert session.owned_browser_pids == set()
            return []
    session.stop_event = OneIteration()
    session.guard = Guard()
    session._guard_loop()
    assert session.browser_identities == {}


def test_proxy_startup_failure_downgrades_without_leaking_resources(monkeypatch, tmp_path):
    plan = copy_workspace_plan(tmp_path)
    monkeypatch.setattr("study_lock.runtime.AllowlistProxyServer", lambda *_args: (_ for _ in ()).throw(OSError("port unavailable")))
    session = StudyLockSession(tmp_path, plan, today=date(2026, 7, 28))
    assert session.start().status is LockState.SAFE_CONFIG
    assert session.health_error == "port unavailable"
    assert session.proxy is None


def test_guard_failure_still_cleans_up_when_state_write_fails(monkeypatch, tmp_path):
    session = StudyLockSession(tmp_path, tmp_path / "plan.md")
    class FailedGuard:
        def inspect_all(self):
            raise RuntimeError("failed")
    class Event:
        def wait(self, _timeout):
            return False
        def set(self):
            pass
    session.guard = FailedGuard()
    session.stop_event = Event()
    monkeypatch.setattr(session.controller, "_set_state", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))
    session._guard_loop()
    assert session.controller.state.status is LockState.SAFE_CONFIG
    assert session.guard is None
    assert "disk full" in session.cleanup_errors


def test_start_returns_current_safe_state_when_guard_fails_immediately(monkeypatch, tmp_path):
    session = StudyLockSession(tmp_path, copy_workspace_plan(tmp_path), today=date(2026, 7, 28))
    real_thread = threading.Thread
    class ImmediateGuardThread:
        def start(self):
            session._fail_safe(RuntimeError("immediate guard failure"), "guard_failed")
        def join(self, **_kwargs):
            pass
    def thread_factory(*args, **kwargs):
        if kwargs.get("target") == session._guard_loop:
            return ImmediateGuardThread()
        return real_thread(*args, **kwargs)
    monkeypatch.setattr("study_lock.runtime.threading.Thread", thread_factory)
    assert session.start().status is LockState.SAFE_CONFIG
