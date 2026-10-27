from dataclasses import dataclass

import psutil

from study_lock.process_guard import ProcessGuard


@dataclass
class FakeProcess:
    process_name: str
    account: str = "user"
    process_id: int = 1
    executable_path: str | None = None
    terminated: bool = False

    def name(self) -> str:
        return self.process_name

    def username(self) -> str:
        return self.account

    @property
    def pid(self) -> int:
        return self.process_id

    def terminate(self) -> None:
        self.terminated = True

    def exe(self) -> str:
        if self.executable_path is None:
            raise RuntimeError("executable unavailable")
        return self.executable_path


def test_allowed_process_is_ignored():
    process = FakeProcess("Code.exe")
    guard = ProcessGuard({"code.exe"}, simulation=False)

    result = guard.inspect(process)

    assert result.action == "allow"
    assert process.terminated is False


def test_simulation_logs_would_block_without_terminating_process():
    process = FakeProcess("Notepad.exe")
    guard = ProcessGuard({"code.exe"}, simulation=True)

    result = guard.inspect(process)

    assert result.action == "would_block"
    assert process.terminated is False


def test_protected_process_is_never_terminated():
    process = FakeProcess("Explorer.exe", account="SYSTEM")
    guard = ProcessGuard(set(), simulation=False)

    result = guard.inspect(process)

    assert result.action == "protected"
    assert process.terminated is False


def test_unlisted_user_process_is_terminated_in_enforcement_mode():
    process = FakeProcess("Notepad.exe")
    guard = ProcessGuard({"code.exe"}, simulation=False)

    result = guard.inspect(process)

    assert result.action == "blocked"
    assert process.terminated is True


def test_owned_chrome_is_allowed_while_ordinary_chrome_is_blocked():
    owned = FakeProcess("chrome.exe", process_id=42)
    ordinary = FakeProcess("chrome.exe", process_id=43)
    guard = ProcessGuard(
        {"chrome.exe"},
        simulation=False,
        owned_process_ids={42},
        restricted_process_names={"chrome.exe"},
    )

    owned_result = guard.inspect(owned)
    ordinary_result = guard.inspect(ordinary)

    assert owned_result.action == "allow"
    assert ordinary_result.action == "blocked"
    assert ordinary.terminated is True


def test_windows_system_ui_process_is_protected():
    process = FakeProcess(
        "StartMenuExperienceHost.exe",
        executable_path=r"C:\Windows\SystemApps\Microsoft.Windows.StartMenuExperienceHost\StartMenuExperienceHost.exe",
    )
    guard = ProcessGuard(set(), simulation=False)

    result = guard.inspect(process)

    assert result.action == "protected"
    assert process.terminated is False


def test_codex_and_chatgpt_runtime_processes_are_protected():
    process_names = {
        "ChatGPT.exe",
        "codex.exe",
        "codex-code-mode-host.exe",
        "codex-command-runner-0.146.0-alpha.3.1.exe",
        "node_repl.exe",
    }

    for process_name in process_names:
        process = FakeProcess(process_name)
        result = ProcessGuard(set(), simulation=False).inspect(process)

        assert result.action == "protected"
        assert process.terminated is False


def test_inspect_all_applies_guard_to_each_process(monkeypatch):
    processes = [FakeProcess("code.exe", process_id=10), FakeProcess("notepad.exe", process_id=11)]
    monkeypatch.setattr(psutil, "process_iter", lambda _attrs: processes)

    results = ProcessGuard({"code.exe"}, simulation=True).inspect_all()

    assert [result.action for result in results] == ["allow", "would_block"]
