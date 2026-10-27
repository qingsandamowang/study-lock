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
    collect_owned_processes,
    find_chrome_executable,
    launch_controlled_browser,
    stop_controlled_browser,
    wait_for_owned_processes,
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
        browser_stopper: Callable[[set[int], Path | None, dict[int, float]], None] = stop_controlled_browser,
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
        self.browser_identities: dict[int, float] = {}
        self.health_error: str | None = None
        self.cleanup_errors: list[str] = []
        self._stop_lock = threading.Lock()
        self.browser_profile_dir: Path | None = None
        self.browser_status = "not started"
        self.logged_guard_events: set[tuple[str, str]] = set()
        self.plan_allowed_apps: set[str] = set()
        self.plan_allowed_domains: set[str] = set()

    @property
    def events_path(self) -> Path:
        return self.workspace_root / "study-lock/runtime/events.jsonl"

    def start(self) -> RuntimeState:
        if self.guard_thread is not None and self.guard_thread.is_alive():
            return self.controller.state
        self.health_error = None
        try:
            return self._start_runtime()
        except Exception as exc:
            return self._fail_safe(exc, "runtime_failed")

    def _start_runtime(self) -> RuntimeState:
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
                self.browser_identities.update(wait_for_owned_processes(self.browser_root_pids, self.browser_profile_dir))
                self.owned_browser_pids.update(self.browser_identities)
                self.browser_status = "controlled Chrome started"
            except Exception as exc:
                return self._fail_safe(exc, "browser_safe_config")

        self.guard = ProcessGuard(
            allowed_apps,
            simulation=self.simulation,
            owned_process_ids=self.owned_browser_pids,
            owned_process_identities=self.browser_identities,
            restricted_process_names={CHROME_PROCESS_NAME},
        )
        self.stop_event.clear()
        self.guard_thread = threading.Thread(target=self._guard_loop, daemon=True)
        self.guard_thread.start()
        return self.controller.state

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
        self.browser_identities.update(wait_for_owned_processes(self.browser_root_pids, self.browser_profile_dir))
        self.owned_browser_pids.update(self.browser_identities)
        return process

    def _guard_loop(self) -> None:
        try:
            while not self.stop_event.wait(1.0):
                guard = self.guard
                if guard is None:
                    return
                if self.browser_root_pids:
                    fresh = collect_owned_processes(self.browser_root_pids, self.browser_profile_dir, self.browser_identities)
                    self.browser_identities.clear()
                    self.browser_identities.update(fresh)
                    self.owned_browser_pids.clear()
                    self.owned_browser_pids.update(fresh)
                for result in guard.inspect_all():
                    if result.action in {"would_block", "blocked", "error"} and should_log_guard_event(self.logged_guard_events, result):
                        append_event(self.events_path, "process_guard", {"process": result.process_name, "action": result.action, "reason": result.reason})
        except Exception as exc:
            self._fail_safe(exc, "guard_failed")

    def _fail_safe(self, exc: Exception, event: str) -> RuntimeState:
        self.health_error = str(exc)
        # Set memory before I/O: disk failure must not hide the degraded status.
        self.controller.state = RuntimeState(self.today, LockState.SAFE_CONFIG, str(self.plan_path))
        try:
            self.controller._set_state(LockState.SAFE_CONFIG)
            append_event(self.events_path, event, {"reason": str(exc)})
        except OSError as write_error:
            self.cleanup_errors.append(str(write_error))
        finally:
            self.stop()
        return self.controller.state

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
        # Detach once under a short lock; joins and shutdown must never hold it.
        with self._stop_lock:
            proxy, proxy_thread, guard_thread = self.proxy, self.proxy_thread, self.guard_thread
            roots, profile, identities = set(self.browser_root_pids), self.browser_profile_dir, dict(self.browser_identities)
            self.proxy = self.proxy_thread = self.guard_thread = self.guard = None
            self.browser_process = self.browser_profile_dir = None
            self.browser_root_pids.clear()
            self.owned_browser_pids.clear()
            self.browser_identities.clear()
        def cleanup(action):
            try:
                action()
            except Exception as exc:
                self.cleanup_errors.append(str(exc))
        if proxy is not None:
            if proxy_thread is None or proxy_thread.is_alive():
                cleanup(proxy.shutdown)
            cleanup(proxy.server_close)
        for thread in (proxy_thread, guard_thread):
            if thread is not None and thread is not threading.current_thread():
                cleanup(lambda thread=thread: thread.join(timeout=2))
        if roots or identities:
            cleanup(lambda: self.browser_stopper(roots, profile, identities))
        self.browser_status = "stopped"
