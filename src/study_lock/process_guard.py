from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROTECTED_PROCESS_NAMES = frozenset(
    {
        "system",
        "registry",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "svchost.exe",
        "explorer.exe",
        "dwm.exe",
        "winlogon.exe",
        "python.exe",
        "pythonw.exe",
        "study-lock.exe",
        "study_lock.exe",
        "chatgpt.exe",
        "codex.exe",
        "codex-code-mode-host.exe",
        "node_repl.exe",
        "applicationframehost.exe",
        "conhost.exe",
        "ctfmon.exe",
        "inputapp.exe",
        "pickerhost.exe",
        "runtimebroker.exe",
        "searchapp.exe",
        "searchfilterhost.exe",
        "searchhost.exe",
        "searchprotocolhost.exe",
        "shellhost.exe",
        "shellexperiencehost.exe",
        "sihost.exe",
        "screenclippinghost.exe",
        "snippingtool.exe",
        "startmenuexperiencehost.exe",
        "systemsettings.exe",
        "taskhost.exe",
        "taskhostw.exe",
        "textinputhost.exe",
        "msedgewebview2.exe",
    }
)


@dataclass(frozen=True)
class GuardResult:
    process_name: str
    action: str
    reason: str


def _is_windows_system_process(process: Any) -> bool:
    try:
        executable = Path(str(process.exe())).resolve()
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
    except Exception:
        return False
    return executable == system_root or system_root in executable.parents


def _is_codex_runtime_process(process_name: str) -> bool:
    return process_name.startswith("codex-command-runner-")


class ProcessGuard:
    def __init__(
        self,
        allowed_apps: set[str],
        *,
        simulation: bool = True,
        protected_names: set[str] | None = None,
        owned_process_ids: set[int] | None = None,
        owned_process_identities: dict[int, float] | None = None,
        restricted_process_names: set[str] | None = None,
    ) -> None:
        self.allowed_apps = {name.lower() for name in allowed_apps}
        self.simulation = simulation
        self.protected_names = {
            name.lower() for name in (protected_names or PROTECTED_PROCESS_NAMES)
        }
        self.owned_process_ids = owned_process_ids if owned_process_ids is not None else set()
        self.owned_process_identities = owned_process_identities
        self.restricted_process_names = {
            name.lower() for name in (restricted_process_names or set())
        }

    def inspect(self, process: Any) -> GuardResult:
        try:
            process_name = str(process.name()).lower()
        except Exception:
            return GuardResult("<unknown>", "skip", "process name unavailable")

        try:
            process_id = int(process.pid)
        except Exception:
            process_id = None

        account = ""
        try:
            account = str(process.username()).upper()
        except Exception:
            pass

        if process_id in self.owned_process_ids:
            try:
                verified = self.owned_process_identities is None or process.create_time() == self.owned_process_identities.get(process_id)
            except Exception:
                verified = False
            if verified:
                return GuardResult(process_name, "allow", "process is owned by Study Lock")
        if (
            process_name in self.protected_names
            or _is_codex_runtime_process(process_name)
            or account in {"SYSTEM", "NT AUTHORITY\\SYSTEM"}
            or _is_windows_system_process(process)
        ):
            return GuardResult(process_name, "protected", "protected process or account")

        if process_name in self.restricted_process_names:
            if self.simulation:
                return GuardResult(process_name, "would_block", "restricted browser process")
            try:
                process.terminate()
            except Exception as exc:
                return GuardResult(process_name, "error", f"terminate failed: {exc}")
            return GuardResult(process_name, "blocked", "ordinary browser process is not owned")

        if process_name in self.allowed_apps:
            return GuardResult(process_name, "allow", "application is allowlisted")

        if self.simulation:
            return GuardResult(process_name, "would_block", "simulation mode")

        try:
            process.terminate()
        except Exception as exc:
            return GuardResult(process_name, "error", f"terminate failed: {exc}")
        return GuardResult(process_name, "blocked", "unlisted user process terminated")

    def inspect_all(self) -> list[GuardResult]:
        import psutil

        results = []
        for process in psutil.process_iter(["name", "username"]):
            results.append(self.inspect(process))
        return results
