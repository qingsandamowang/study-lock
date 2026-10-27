import subprocess
from pathlib import Path

from study_lock.startup import (
    TASK_NAME,
    build_install_command,
    build_remove_command,
    install_startup,
    remove_startup,
)


def test_install_command_targets_one_user_task_and_exact_launcher(tmp_path: Path):
    command = build_install_command(
        "python.exe",
        tmp_path / "launcher.py",
    )

    assert command[:4] == ["schtasks", "/Create", "/TN", TASK_NAME]
    assert "/SC" in command and command[command.index("/SC") + 1] == "ONLOGON"
    assert str(tmp_path / "launcher.py") in command[command.index("/TR") + 1]
    assert "/F" in command


def test_remove_command_targets_only_the_study_lock_task():
    assert build_remove_command() == ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]


def test_startup_mutations_use_injected_runner():
    calls: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    install_startup("python.exe", tmp_path := Path("C:/study-lock/launcher.py"), runner=runner)
    remove_startup(runner=runner)

    assert calls[0][0:4] == ["schtasks", "/Create", "/TN", TASK_NAME]
    assert calls[1] == build_remove_command()
