"""Read-only configuration checks. No runtime sessions or external requests."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .browser import find_chrome_executable
from .domain_rules import normalize_domain
from .plan_parser import parse_plan
from .proxy import WEB_PORTS
from .resources import resolve_resource_location
from .storage import resolve_workspace_path


def valid_domain(value: str) -> bool:
    try:
        labels = normalize_domain(value).split(".")
        return len(value) <= 253 and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
    except ValueError:
        return False


def check_config(workspace: Path, plan_path: Path, *, today: date | None = None, check_browser: bool = False, browser: Path | None = None, mode: str = "reminder") -> dict:
    root = Path(workspace).resolve()
    plan_path = Path(plan_path).resolve()
    checks: list[dict[str, str]] = []

    def add(code, level, message):
        checks.append({"code": code, "level": level, "message": message})

    def local_path(code, path, *, must_exist):
        if not path.is_relative_to(root):
            add(code, "error", "Path must stay inside workspace")
            return
        if path.exists():
            if code == "record_path" and not path.is_file():
                add(code, "error", "Learning record must be a file")
            else:
                add(code, "ok", "Local path exists")
            return
        ancestor = next((parent for parent in path.parents if parent.exists()), root)
        if not ancestor.is_dir():
            add(code, "error", "An ancestor of the path is not a directory")
        else:
            add(code, "error" if must_exist else "warning", "Local path is missing" if must_exist else "Learning record has not been created yet")

    add("workspace", "ok" if root.is_dir() else "error", "Workspace directory exists" if root.is_dir() else "Workspace must be an existing directory")
    plan = None
    if not plan_path.is_relative_to(root):
        add("plan_path", "error", "Plan must stay inside workspace")
    else:
        try:
            plan = parse_plan(plan_path)
            add("plan_syntax", "ok", f"Parsed {len(plan.workflow or plan.tasks)} study steps")
        except (OSError, ValueError) as exc:
            add("plan_syntax", "error", str(exc))
    if plan is not None:
        expected = today or date.today()
        add("plan_date", "ok" if plan.plan_date == expected else "error", f"Plan date {plan.plan_date.isoformat()}; expected {expected.isoformat()}")
        try:
            local_path("record_path", resolve_workspace_path(root, plan.learning_record), must_exist=False)
        except (OSError, ValueError) as exc:
            add("record_path", "error", str(exc))
        bad_apps = [app for app in plan.allowed_apps if not re.fullmatch(r"[\w .()-]+\.exe", app, re.IGNORECASE)]
        add("app_rules", "error" if bad_apps else "ok", "Applications must be executable names ending in .exe" if bad_apps else f"Validated {len(plan.allowed_apps)} application rules")
        bad_domains = [domain for domain in plan.allowed_domains if not valid_domain(domain)]
        add("domain_rules", "error" if bad_domains else "ok", "Domain rules must contain hostnames without ports, wildcards or URL components" if bad_domains else f"Validated {len(plan.allowed_domains)} domain rules")
        for index, resource in enumerate(plan.resources, 1):
            code = f"resource_{index}"
            # Keep URL semicolons intact; local resource groups use the same separator as the UI.
            locations = [resource.location] if "://" in resource.location or Path(resource.location).is_absolute() and Path(resource.location).exists() else re.split(r"[;；]", resource.location)
            for location in locations:
                try:
                    target = resolve_resource_location(root, location.strip())
                    if isinstance(target, str):
                        parsed = urlparse(target)
                        if not parsed.hostname or not valid_domain(parsed.hostname) or parsed.username or parsed.password:
                            raise ValueError("Resource URL must contain a valid hostname and no credentials")
                        port = parsed.port or (443 if parsed.scheme == "https" else 80)
                        if port not in WEB_PORTS:
                            add(code, "error" if mode == "enforce" else "warning", f"Resource port {port} is unsupported by the controlled proxy (only 80/443): {resource.title}")
                        else:
                            add(code, "ok", f"URL syntax valid: {resource.title} (network availability not checked)")
                    else:
                        local_path(code, target, must_exist=resource.kind != "记录")
                except (OSError, ValueError) as exc:
                    add(code, "error", str(exc))
    if check_browser or browser is not None:
        executable = browser if browser is not None else find_chrome_executable()
        exists = executable is not None and Path(executable).is_file()
        add("browser", "ok" if exists else "error", "Browser executable exists; it was not launched" if exists else "Browser executable was not found")
    else:
        add("browser", "ok", "Optional browser check skipped")
    return {"schema_version": 1, "target_mode": mode, "ok": not any(item["level"] == "error" for item in checks), "checks": checks}
