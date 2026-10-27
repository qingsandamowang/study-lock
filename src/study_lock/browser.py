from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable

import psutil


CHROME_PROCESS_NAME = "chrome.exe"


def find_chrome_executable(candidates: Iterable[Path] | None = None) -> Path | None:
    if candidates is None:
        candidates = _default_chrome_candidates()
    seen: set[Path] = set()
    for candidate in candidates:
        path = Path(candidate)
        if path in seen:
            continue
        seen.add(path)
        if path.is_file():
            return path
    return None


def _default_chrome_candidates() -> list[Path]:
    candidates: list[Path] = []
    located = shutil.which(CHROME_PROCESS_NAME) or shutil.which("chrome")
    if located:
        candidates.append(Path(located))

    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if not root:
            continue
        candidates.append(Path(root) / "Google/Chrome/Application/chrome.exe")
    return candidates


def build_browser_command(
    executable: str,
    profile_dir: Path,
    *,
    proxy_port: int,
    url: str | None = None,
) -> list[str]:
    command = [
        executable,
        f"--user-data-dir={Path(profile_dir)}",
        f"--proxy-server=http://127.0.0.1:{proxy_port}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if url:
        command.append(url)
    return command


def launch_controlled_browser(
    executable: Path | str,
    profile_dir: Path,
    *,
    proxy_port: int,
    url: str | None = None,
) -> subprocess.Popen:
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = build_browser_command(
        str(executable),
        profile_dir,
        proxy_port=proxy_port,
        url=url,
    )
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(command, creationflags=creationflags)


def close_processes_by_name(process_name: str = CHROME_PROCESS_NAME) -> list[int]:
    matches = []
    normalized = process_name.lower()
    for process in psutil.process_iter(["name"]):
        try:
            if str(process.info.get("name") or "").lower() == normalized:
                matches.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    for process in matches:
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _, alive = psutil.wait_procs(matches, timeout=3)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return [process.pid for process in matches]


def _profile_argument_matches(cmdline: list[str] | None, profile_dir: Path) -> bool:
    expected = str(Path(profile_dir)).replace("/", "\\").rstrip("\\").lower()
    for argument in cmdline or []:
        value = str(argument).strip().strip('"')
        if not value.lower().startswith("--user-data-dir="):
            continue
        actual = value.split("=", 1)[1].replace("/", "\\").rstrip("\\").lower()
        if actual == expected:
            return True
    return False


def collect_owned_process_ids(
    root_pids: set[int],
    profile_dir: Path | None = None,
) -> set[int]:
    owned: set[int] = set()
    for root_pid in root_pids:
        try:
            root = psutil.Process(root_pid)
            owned.add(root.pid)
            owned.update(child.pid for child in root.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if profile_dir is not None:
        for process in psutil.process_iter(["name", "cmdline"]):
            try:
                if str(process.info.get("name") or "").lower() != CHROME_PROCESS_NAME:
                    continue
                if _profile_argument_matches(process.info.get("cmdline"), profile_dir):
                    owned.add(process.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    return owned


def wait_for_owned_process_ids(
    root_pids: set[int],
    profile_dir: Path,
    *,
    timeout: float = 1.5,
) -> set[int]:
    deadline = time.monotonic() + timeout
    owned: set[int] = set()
    while time.monotonic() < deadline:
        owned = collect_owned_process_ids(root_pids, profile_dir)
        if len(owned) > len(root_pids):
            return owned
        if not any(psutil.pid_exists(pid) for pid in root_pids):
            return owned
        time.sleep(0.05)
    return owned


def stop_controlled_browser(
    root_pids: set[int],
    profile_dir: Path | None = None,
    owned_pids: set[int] | None = None,
) -> None:
    processes = []
    process_ids = collect_owned_process_ids(root_pids, profile_dir)
    process_ids.update(owned_pids or set())
    for pid in process_ids:
        try:
            processes.append(psutil.Process(pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    for process in processes:
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _, alive = psutil.wait_procs(processes, timeout=3)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
