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
    return set(collect_owned_processes(root_pids, profile_dir))


def collect_owned_processes(
    root_pids: set[int],
    profile_dir: Path | None = None,
    identities: dict[int, float] | None = None,
) -> dict[int, float]:
    """Return fresh PID/create-time identities backed by prior identity or profile evidence."""
    owned: dict[int, float] = {}
    known = dict(identities or {})
    for root_pid in set(root_pids) | known.keys():
        try:
            root = psutil.Process(root_pid)
            if root_pid in known:
                verified = root.create_time() == known[root_pid]
            else:
                verified = profile_dir is not None and root.name().lower() == CHROME_PROCESS_NAME and _profile_argument_matches(root.cmdline(), profile_dir)
            if not verified:
                continue
            owned[root.pid] = root.create_time()
            for child in root.children(recursive=True):
                if child.name().lower() == CHROME_PROCESS_NAME:
                    owned[child.pid] = child.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if profile_dir is not None:
        for process in psutil.process_iter(["name", "cmdline"]):
            try:
                if str(process.info.get("name") or "").lower() != CHROME_PROCESS_NAME:
                    continue
                if _profile_argument_matches(process.info.get("cmdline"), profile_dir):
                    owned[process.pid] = process.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    return owned


def wait_for_owned_processes(root_pids: set[int], profile_dir: Path, *, timeout: float = 1.5) -> dict[int, float]:
    deadline = time.monotonic() + timeout
    owned: dict[int, float] = {}
    while time.monotonic() < deadline:
        owned = collect_owned_processes(root_pids, profile_dir, owned)
        if len(owned) > len(root_pids) or not any(psutil.pid_exists(pid) for pid in root_pids):
            return owned
        time.sleep(0.05)
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
    owned_pids: set[int] | dict[int, float] | None = None,
) -> None:
    processes = []
    identities = owned_pids if isinstance(owned_pids, dict) else {}
    process_ids = collect_owned_processes(root_pids, profile_dir, identities)
    for pid, created in identities.items():
        try:
            if psutil.Process(pid).create_time() == created:
                process_ids[pid] = created
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    for pid, created in process_ids.items():
        try:
            process = psutil.Process(pid)
            if process.create_time() == created:
                processes.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    for process in processes:
        try:
            if process.create_time() == process_ids[process.pid]:
                process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _, alive = psutil.wait_procs(processes, timeout=3)
    for process in alive:
        try:
            if process.create_time() == process_ids[process.pid]:
                process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
