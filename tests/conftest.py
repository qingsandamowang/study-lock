"""Never inspect or terminate host processes during the test suite."""
import psutil
import pytest


@pytest.fixture(autouse=True)
def isolate_host_processes(monkeypatch):
    monkeypatch.setattr(psutil, "process_iter", lambda *_args, **_kwargs: [])

    def unavailable(pid, *_args, **_kwargs):
        raise psutil.NoSuchProcess(pid)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Tests must use fake processes; host termination is forbidden")

    monkeypatch.setattr(psutil.Process, "terminate", forbidden)
    monkeypatch.setattr(psutil.Process, "kill", forbidden)
    monkeypatch.setattr(psutil, "Process", unavailable)
    monkeypatch.setattr(psutil, "pid_exists", lambda _pid: False)
