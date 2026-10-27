from __future__ import annotations

import os
import threading
import webbrowser
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .browser import (
    CHROME_PROCESS_NAME,
    close_processes_by_name,
    collect_owned_process_ids,
    find_chrome_executable,
    launch_controlled_browser,
    stop_controlled_browser,
    wait_for_owned_process_ids,
)
from .controller import StudyLockController
from .domain_rules import normalize_domain
from .process_guard import ProcessGuard
from .proxy import AllowlistProxyServer
from .recovery import RecoveryGate
from .state import LockState, RuntimeState, append_event
from .ui import load_overrides


def should_log_guard_event(seen: set[tuple[str, str]], result) -> bool:
    key = (result.process_name, result.action)
    if key in seen:
        return False
    seen.add(key)
    return True


class StudyLockSession:
    def __init__(
        self,
        workspace_root: Path,
        plan_path: Path,
        *,
        today: date | None = None,
        simulation: bool = True,
        chrome_finder: Callable[[], Path | None] = find_chrome_executable,
        ordinary_chrome_closer: Callable[[], object] = close_processes_by_name,
        browser_launcher: Callable[..., object] = launch_controlled_browser,
        browser_stopper: Callable[[set[int], Path | None, set[int]], None] = stop_controlled_browser,
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self.plan_path = Path(plan_path)
        self.today = today or date.today()
        self.simulation = simulation
        self.chrome_finder = chrome_finder
        self.ordinary_chrome_closer = ordinary_chrome_closer
        self.browser_launcher = browser_launcher
        self.browser_stopper = browser_stopper
        self.controller = StudyLockController(
            self.workspace_root,
            self.plan_path,
            today=self.today,
            simulation=simulation,
        )
        self.proxy: AllowlistProxyServer | None = None
        self.proxy_thread: threading.Thread | None = None
        self.guard: ProcessGuard | None = None
        self.guard_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.browser_process: object | None = None
        self.browser_root_pids: set[int] = set()
        self.owned_browser_pids: set[int] = set()
        self.browser_profile_dir: Path | None = None
        self.browser_status = "not started"
        self.logged_guard_events: set[tuple[str, str]] = set()
        self.plan_allowed_apps: set[str] = set()
        self.plan_allowed_domains: set[str] = set()

    @property
    def events_path(self) -> Path:
        return self.workspace_root / "study-lock/runtime/events.jsonl"

    def start(self) -> RuntimeState:
        state = self.controller.start()
        if state.status is not LockState.LOCKED or self.controller.plan is None:
            return state

        overrides = load_overrides(self.workspace_root / "study-lock/runtime", self.today)
        self.plan_allowed_domains = set(self.controller.plan.allowed_domains)
        self.plan_allowed_apps = set(self.controller.plan.allowed_apps)
        for resource in self.controller.plan.resources:
            parsed = urlparse(resource.location)
            if parsed.scheme in {"http", "https"} and parsed.hostname:
                try:
                    self.plan_allowed_domains.add(normalize_domain(parsed.hostname))
                except ValueError:
                    pass
        allowed_domains = self.plan_allowed_domains | overrides.domains
        allowed_apps = self.plan_allowed_apps | overrides.apps
        self.proxy = AllowlistProxyServer(allowed_domains)
        self.proxy_thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
        self.proxy_thread.start()

        if self.simulation:
            self.browser_status = "simulation: controlled browser not started"
        else:
            try:
                executable = self.chrome_finder()
                if executable is None:
                    raise FileNotFoundError("Google Chrome executable was not found")
                self.ordinary_chrome_closer()
                first_domain = sorted(allowed_domains)[0] if allowed_domains else None
                self.browser_profile_dir = (
                    self.workspace_root / "study-lock/runtime/browser-profiles" / self.today.isoformat()
                )
                self.browser_process = self.browser_launcher(
                    executable,
                    self.browser_profile_dir,
                    proxy_port=self.proxy.proxy_port,
                    url=f"https://{first_domain}" if first_domain else None,
                )
                self.browser_root_pids = {int(self.browser_process.pid)}
                self.owned_browser_pids.update(
                    wait_for_owned_process_ids(self.browser_root_pids, self.browser_profile_dir)
                )
                self.browser_status = "controlled Chrome started"
            except Exception as exc:
                append_event(
                    self.events_path,
                    "browser_safe_config",
                    {"reason": str(exc)},
                )
                self.stop()
                return self.controller._set_state(LockState.SAFE_CONFIG)

        self.guard = ProcessGuard(
            allowed_apps,
            simulation=self.simulation,
            owned_process_ids=self.owned_browser_pids,
            restricted_process_names={CHROME_PROCESS_NAME},
        )
        self.stop_event.clear()
        self.guard_thread = threading.Thread(target=self._guard_loop, daemon=True)
        self.guard_thread.start()
        return state

    def refresh_overrides(self) -> None:
        overrides = load_overrides(self.workspace_root / "study-lock/runtime", self.today)
        allowed_apps = self.plan_allowed_apps | overrides.apps
        allowed_domains = self.plan_allowed_domains | overrides.domains
        if self.guard is not None:
            self.guard.allowed_apps.clear()
            self.guard.allowed_apps.update(allowed_apps)
        if self.proxy is not None:
            self.proxy.policy.allowed_domains.clear()
            self.proxy.policy.allowed_domains.update(allowed_domains)

    def open_url(self, url: str) -> object:
        """Open a learning URL in the controlled browser when enforcement is active."""
        if self.simulation or self.proxy is None or self.browser_profile_dir is None:
            return webbrowser.open(url)
        return self._open_in_controlled_browser(url)

    def open_file(self, path: Path) -> object:
        """Open a local learning file without creating an unowned browser process."""
        path = Path(path).resolve()
        if self.simulation or self.proxy is None or self.browser_profile_dir is None:
            if not hasattr(os, "startfile"):
                raise OSError("当前系统没有可用的文件打开器")
            return os.startfile(str(path))
        return self._open_in_controlled_browser(path.as_uri())

    def _open_in_controlled_browser(self, target: str) -> object:
        executable = self.chrome_finder()
        if executable is None:
            raise FileNotFoundError("Google Chrome executable was not found")
        process = self.browser_launcher(
            executable,
            self.browser_profile_dir,
            proxy_port=self.proxy.proxy_port,
            url=target,
        )
        self.browser_root_pids.add(int(process.pid))
        self.owned_browser_pids.update(
            wait_for_owned_process_ids(self.browser_root_pids, self.browser_profile_dir)
        )
        return process

    def _guard_loop(self) -> None:
        while not self.stop_event.wait(1.0):
            if self.guard is None:
                return
            if self.browser_root_pids:
                self.owned_browser_pids.update(
                    collect_owned_process_ids(self.browser_root_pids, self.browser_profile_dir)
                )
            for result in self.guard.inspect_all():
                if (
                    result.action in {"would_block", "blocked", "error"}
                    and should_log_guard_event(self.logged_guard_events, result)
                ):
                    append_event(
                        self.events_path,
                        "process_guard",
                        {"process": result.process_name, "action": result.action, "reason": result.reason},
                    )

    def request_unlock(self) -> RuntimeState:
        state = self.controller.request_unlock()
        if state.status is LockState.UNLOCKED:
            self.stop()
        return state

    def request_recovery(self, gate: RecoveryGate, phrase: str, *, now: float) -> RuntimeState:
        state = self.controller.enter_recovery(gate, phrase, now=now)
        if state.status is LockState.RECOVERY:
            self.stop()
        return state

    def stop(self) -> None:
        self.stop_event.set()
        if self.proxy is not None:
            self.proxy.shutdown()
            self.proxy.server_close()
        if self.proxy_thread is not None:
            self.proxy_thread.join(timeout=2)
        if self.guard_thread is not None:
            self.guard_thread.join(timeout=2)
        if self.browser_root_pids:
            self.browser_stopper(
                self.browser_root_pids,
                self.browser_profile_dir,
                self.owned_browser_pids,
            )
        self.browser_root_pids.clear()
        self.owned_browser_pids.clear()
        self.browser_process = None
        self.browser_profile_dir = None
        self.proxy = None
        self.proxy_thread = None
        self.guard_thread = None
        self.guard = None
        self.browser_status = "stopped"
