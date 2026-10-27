from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .plan_parser import parse_plan
from .notifications import (
    load_pushplus_config,
    mark_missed_notification_sent,
    missed_notification_marker_path,
    send_pushplus,
    should_send_missed_notification,
)
from .runtime import StudyLockSession
from .progress import load_daily_progress, progress_path
from .state import LockState, RuntimeState, append_event, save_state
from .startup import install_startup, remove_startup, startup_exists


def launch_panel(*args, **kwargs):
    from .ui import launch_panel as _launch_panel

    return _launch_panel(*args, **kwargs)


def launch_recovery_panel(*args, **kwargs):
    from .ui import launch_recovery_panel as _launch_recovery_panel

    return _launch_recovery_panel(*args, **kwargs)


@dataclass(frozen=True)
class SimulationReport:
    state: LockState
    enforced: bool
    message: str
    plan_title: str | None = None


def notify_previous_incomplete_plan(workspace_root: Path, current_date: date) -> bool:
    config = load_pushplus_config(workspace_root)
    if not config.enabled or not config.token.strip():
        return False
    previous_date = current_date - timedelta(days=1)
    previous_path = Path(workspace_root) / "study-plans" / "daily" / f"{previous_date.isoformat()}.md"
    if not previous_path.is_file():
        return False
    try:
        plan = parse_plan(previous_path)
    except (OSError, ValueError):
        return False
    previous_progress_path = progress_path(workspace_root, previous_date)
    previous_progress = load_daily_progress(workspace_root, previous_date)
    if plan.is_complete() and (not previous_progress_path.is_file() or previous_progress.checked_in):
        return False
    marker = missed_notification_marker_path(workspace_root, previous_date)
    if not should_send_missed_notification(marker):
        return False
    pending = [task.label for task in (plan.workflow or plan.tasks) if not task.completed][:3]
    pending_text = "\n".join(f"- {item}" for item in pending) or "- 昨日任务已完成，但没有完成打卡"
    result = send_pushplus(
        config,
        "Study Lock · 昨日学习未完成或未打卡",
        f"{previous_date.isoformat()} 的学习任务没有完成打卡，今天需要补做或确认。\n\n待处理内容：\n{pending_text}",
    )
    if result.ok:
        mark_missed_notification_sent(marker)
        return True
    return False


def simulate_plan(
    plan_path: Path,
    workspace_root: Path,
    *,
    today: date | None = None,
) -> SimulationReport:
    current_date = today or date.today()
    try:
        plan = parse_plan(Path(plan_path))
    except (OSError, ValueError) as exc:
        message = f"SAFE_CONFIG: {exc}"
        append_event(
            Path(workspace_root) / "study-lock/runtime/events.jsonl",
            "simulation_safe_config",
            {"plan": str(plan_path), "reason": str(exc)},
        )
        return SimulationReport(LockState.SAFE_CONFIG, False, message)

    if plan.plan_date != current_date:
        message = f"SAFE_CONFIG: plan date is {plan.plan_date.isoformat()}, expected {current_date.isoformat()}"
        append_event(
            Path(workspace_root) / "study-lock/runtime/events.jsonl",
            "simulation_safe_config",
            {"plan": str(plan_path), "reason": message},
        )
        return SimulationReport(LockState.SAFE_CONFIG, False, message, plan.title)

    message = "LOCKED: simulation only; no processes or browser connections will be changed"
    append_event(
        Path(workspace_root) / "study-lock/runtime/events.jsonl",
        "simulation_locked",
        {"plan": str(plan_path), "apps": sorted(plan.allowed_apps), "domains": sorted(plan.allowed_domains)},
    )
    return SimulationReport(LockState.LOCKED, False, message, plan.title)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="study-lock")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="validate configuration without starting restrictions or writing files")
    doctor.add_argument("--workspace", type=Path, required=True)
    doctor.add_argument("--plan", type=Path, required=True)
    doctor.add_argument("--date", type=date.fromisoformat)
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--check-browser", action="store_true")
    doctor.add_argument("--browser", type=Path)
    doctor.add_argument("--mode", choices=("reminder", "simulate", "enforce"), default="reminder", help="validate for this target mode without starting it")
    stats = subparsers.add_parser("stats", help="export local learning statistics as JSON, CSV and HTML")
    stats.add_argument("--workspace", type=Path, required=True)
    stats.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    stats.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    stats.add_argument("--out", type=Path, required=True)
    simulate = subparsers.add_parser("simulate", help="show lock decisions without enforcement")
    simulate.add_argument("--plan", type=Path, required=True)
    simulate.add_argument("--workspace", type=Path, required=True)
    simulate.add_argument("--date", type=date.fromisoformat)
    ui = subparsers.add_parser("ui", help="open the control panel")
    ui.add_argument("--mode", choices=("reminder", "simulate", "enforce"), default="reminder")
    ui.add_argument("--plan", type=Path, required=True)
    ui.add_argument("--workspace", type=Path, required=True)
    ui.add_argument("--date", type=date.fromisoformat)
    startup = subparsers.add_parser("startup", help="manage the per-user startup task")
    startup.add_argument("action", choices=("install", "remove", "status"))
    startup.add_argument("--python", default=sys.executable)
    startup.add_argument("--launcher", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        from .doctor import check_config
        report = check_config(args.workspace, args.plan, today=args.date, check_browser=args.check_browser, browser=args.browser, mode=args.mode)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"doctor: {'PASS' if report['ok'] else 'FAIL'} (read-only)")
            for item in report["checks"]:
                print(f"[{item['level']}] {item['code']}: {item['message']}")
        return 0 if report["ok"] else 1
    if args.command == "stats":
        from .analytics import collect_stats, export_stats
        try:
            report = collect_stats(args.workspace, args.start, args.end)
            paths = export_stats(report, args.out)
        except (OSError, ValueError) as exc:
            print(f"stats: {exc}")
            return 1
        print(f"stats: {report['totals']['tasks_completed']}/{report['totals']['tasks_total']} tasks; {report['totals']['checked_in_days']} check-ins; {len(report['warnings'])} data issues")
        for path in paths:
            print(path)
        return 0
    if args.command == "simulate":
        report = simulate_plan(args.plan, args.workspace, today=args.date)
        print(f"simulation: state={report.state.value}")
        print(report.message)
        if report.plan_title:
            print(f"plan: {report.plan_title}")
        return 0
    if args.command == "ui":
        current_date = args.date or date.today()
        try:
            plan = parse_plan(args.plan)
        except (OSError, ValueError) as exc:
            print(f"SAFE_CONFIG: {exc}")
            return 1
        if plan.plan_date != current_date:
            print(f"SAFE_CONFIG: plan date is {plan.plan_date.isoformat()}, expected {current_date.isoformat()}")
            return 1
        if args.mode == "reminder":
            save_state(
                Path(args.workspace) / "study-lock/runtime/state.json",
                RuntimeState(current_date, LockState.UNLOCKED, str(args.plan)),
            )
            print("ui: mode=reminder state=UNLOCKED; no process or browser controls enabled")
            threading.Thread(
                target=notify_previous_incomplete_plan,
                args=(args.workspace, current_date),
                daemon=True,
            ).start()
            launch_panel(
                plan,
                args.plan,
                args.workspace,
                current_date=current_date,
                browser_status="系统浏览器不受限制",
                url_opener=webbrowser.open,
                file_opener=None,
                enforce_close_guard=False,
                mode_label="提醒模式",
                reminder_enabled=True,
            )
            return 0
        session = StudyLockSession(
            args.workspace,
            args.plan,
            today=current_date,
            simulation=args.mode == "simulate",
        )
        state = session.start()
        if state.status is LockState.RECOVERY:
            print("ui: state=RECOVERY; opening recovery dashboard")
            try:
                launch_recovery_panel(
                    plan,
                    args.plan,
                    args.workspace,
                    message="紧急恢复标记已生效，今天不会再次启动强制锁定。",
                )
            finally:
                session.stop()
            return 0
        if state.status is not LockState.LOCKED:
            print(f"ui: mode={args.mode} state={state.status.value}")
            try:
                launch_recovery_panel(
                    plan,
                    args.plan,
                    args.workspace,
                    message="计划配置不可用，已进入安全配置状态；未启动进程或网页限制。",
                )
            finally:
                session.stop()
            return 1
        print(f"ui: mode={args.mode} state=LOCKED")
        try:
            launch_panel(
                plan,
                args.plan,
                args.workspace,
                current_date=current_date,
                browser_status=session.browser_status,
                on_overrides_changed=session.refresh_overrides,
                on_unlock=session.request_unlock,
                on_recovery=lambda phrase, gate: session.request_recovery(
                    gate,
                    phrase,
                    now=time.monotonic(),
                ),
                url_opener=session.open_url,
                file_opener=session.open_file,
                enforce_close_guard=args.mode == "enforce",
                mode_label="强制模式" if args.mode == "enforce" else "模拟模式",
                health_provider=lambda: session.health_error,
            )
        finally:
            session.stop()
        return 0
    if args.command == "startup":
        if args.action == "install":
            if args.launcher is None:
                print("startup install requires --launcher")
                return 2
            install_startup(args.python, args.launcher)
            print("startup: installed")
            return 0
        if args.action == "remove":
            remove_startup()
            print("startup: removed")
            return 0
        print(f"startup: {'installed' if startup_exists() else 'not installed'}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
