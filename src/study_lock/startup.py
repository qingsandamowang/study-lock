from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable


TASK_NAME = "CodexStudyLock"
CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def build_install_command(python_executable: str, launcher: Path) -> list[str]:
    task_action = f'"{python_executable}" "{Path(launcher).resolve()}"'
    return ["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON", "/TR", task_action, "/F"]


def build_remove_command() -> list[str]:
    return ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def install_startup(
    python_executable: str,
    launcher: Path,
    *,
    runner: CommandRunner = _default_runner,
) -> None:
    runner(build_install_command(python_executable, launcher))


def remove_startup(*, runner: CommandRunner = _default_runner) -> None:
    runner(build_remove_command())


def startup_exists(*, runner: CommandRunner = _default_runner) -> bool:
    command = ["schtasks", "/Query", "/TN", TASK_NAME]
    try:
        runner(command)
    except subprocess.CalledProcessError:
        return False
    return True
