from pathlib import Path

from study_lock.browser import (
    build_browser_command,
    collect_owned_process_ids,
    find_chrome_executable,
    wait_for_owned_process_ids,
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
