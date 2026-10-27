from pathlib import Path

from study_lock.browser import (
    build_browser_command,
    collect_owned_process_ids,
    find_chrome_executable,
    wait_for_owned_process_ids,
    stop_controlled_browser,
)


def test_browser_command_uses_dedicated_profile_and_local_proxy(tmp_path: Path):
    profile = tmp_path / "managed-browser"

    command = build_browser_command(
        "msedge.exe",
        profile,
        proxy_port=18443,
        url="https://chatgpt.com",
    )

    assert command[0] == "msedge.exe"
    assert f"--user-data-dir={profile}" in command
    assert "--proxy-server=http://127.0.0.1:18443" in command
    assert command[-1] == "https://chatgpt.com"
    assert all("Default" not in item for item in command)


def test_find_chrome_executable_returns_existing_candidate(tmp_path: Path):
    missing = tmp_path / "missing" / "chrome.exe"
    installed = tmp_path / "Google" / "Chrome" / "chrome.exe"
    installed.parent.mkdir(parents=True)
    installed.write_text("", encoding="ascii")

    assert find_chrome_executable([missing, installed]) == installed


def test_collect_owned_process_ids_finds_chrome_children_by_profile(monkeypatch, tmp_path: Path):
    profile = tmp_path / "managed-browser"

    class FakeChrome:
        pid = 42
        info = {
            "name": "chrome.exe",
            "cmdline": ["chrome.exe", f"--user-data-dir={profile}"],
        }
        def create_time(self):
            return 10.0

    monkeypatch.setattr("study_lock.browser.psutil.process_iter", lambda fields: [FakeChrome()])

    assert collect_owned_process_ids(set(), profile) == {42}


def test_wait_for_owned_process_ids_keeps_children_seen_before_launcher_exits(monkeypatch, tmp_path: Path):
    profile = tmp_path / "managed-browser"
    responses = [{1}, {1, 2}]

    monkeypatch.setattr("study_lock.browser.psutil.pid_exists", lambda pid: True)
    monkeypatch.setattr(
        "study_lock.browser.collect_owned_process_ids",
        lambda root_pids, profile_dir: responses.pop(0),
    )

    assert wait_for_owned_process_ids({1}, profile, timeout=0.2) == {1, 2}


def test_root_pid_without_identity_or_profile_proof_is_not_owned(monkeypatch):
    class ReusedProcess:
        pid = 42
        def children(self, recursive):
            return []
    monkeypatch.setattr("study_lock.browser.psutil.Process", lambda _pid: ReusedProcess())
    assert collect_owned_process_ids({42}) == set()


def test_stop_does_not_terminate_a_reused_owned_pid(monkeypatch):
    calls = []
    class ReusedProcess:
        pid = 42
        def create_time(self):
            return 20.0
        def terminate(self):
            calls.append("terminate")
        def children(self, recursive):
            return []
    monkeypatch.setattr("study_lock.browser.psutil.Process", lambda _pid: ReusedProcess())
    monkeypatch.setattr("study_lock.browser.psutil.wait_procs", lambda *_args, **_kwargs: ([], []))
    stop_controlled_browser({42}, owned_pids={42: 10.0})
    assert calls == []


def test_current_child_identity_survives_launcher_exit(monkeypatch):
    import psutil
    from study_lock.browser import collect_owned_processes
    class Child:
        pid = 43
        def create_time(self):
            return 12.0
        def children(self, recursive):
            return []
    def process(pid):
        if pid == 43:
            return Child()
        raise psutil.NoSuchProcess(pid)
    monkeypatch.setattr("study_lock.browser.psutil.Process", process)
    assert collect_owned_processes({42}, identities={42: 10.0, 43: 12.0}) == {43: 12.0}


def test_stop_terminates_only_identity_verified_fake_process(monkeypatch):
    calls = []
    class Owned:
        pid = 42
        def create_time(self):
            return 10.0
        def children(self, recursive):
            return []
        def terminate(self):
            calls.append("terminate")
    monkeypatch.setattr("study_lock.browser.psutil.Process", lambda _pid: Owned())
    monkeypatch.setattr("study_lock.browser.psutil.wait_procs", lambda *_args, **_kwargs: ([], []))
    stop_controlled_browser({42}, owned_pids={42: 10.0})
    assert calls == ["terminate"]
