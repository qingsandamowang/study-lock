from __future__ import annotations

import base64
import calendar
import json
import locale
import subprocess
import threading
import time
import math
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from .domain_rules import normalize_domain
from .models import DailyPlan, LearningResource
from .notifications import PushPlusConfig, load_pushplus_config, save_pushplus_config, send_pushplus
from .planning import detailed_plan_template, save_plan, sync_plan_date_heading
from .plan_parser import parse_plan, write_section_checkbox_state
from .progress import (
    add_focus_seconds,
    CarryoverTask,
    DailyProgress,
    can_check_in,
    carryover_is_unlocked,
    load_daily_progress,
    mark_checked_in,
    prepare_daily_progress,
    progress_path,
    save_daily_progress,
    streak_stats,
)
from .records import ensure_record, record_has_user_content, record_path, save_record
from .recovery import RecoveryGate
from .resources import open_resource
from .timer import FocusStage, TimerState, build_focus_stages, format_remaining, initial_timer_state, pause_timer, reset_timer, start_timer, tick_timer
from .unlock import UnlockResult, validate_unlock


UI_COLORS = {
    "background": "#F4F7FB",
    "surface": "#FFFFFF",
    "primary": "#2F80ED",
    "primary_dark": "#172B4D",
    "text": "#334155",
    "muted": "#64748B",
    "border": "#DCE6F1",
    "blue_soft": "#EAF3FF",
    "green": "#18866B",
    "green_soft": "#E8F6F1",
    "amber": "#C47A1A",
    "amber_soft": "#FFF7E8",
    "disabled": "#94A3B8",
}


def progress_percent(completed: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round(completed * 100 / total)))


def progress_text(completed: int, total: int) -> str:
    return f"进度 {completed} / {total} · {progress_percent(completed, total)}%"


def combined_progress_text(today_completed: int, today_total: int, carryover_completed: int, carryover_total: int) -> str:
    if carryover_total <= 0:
        return progress_text(today_completed, today_total)
    return (
        f"总进度 {today_completed + carryover_completed} / {today_total + carryover_total}"
        f" · 今日 {today_completed} / {today_total} · 补做 {carryover_completed} / {carryover_total}"
    )


def wheel_scroll_units(delta: int) -> int:
    if delta == 0:
        return 0
    return -1 if delta > 0 else 1


def calendar_day_state(day: date, current_day: date, progress: DailyProgress | None) -> str:
    if progress is not None and progress.checked_in:
        return "checked"
    if day == current_day:
        return "today"
    if day < current_day and progress is not None:
        return "missed"
    if day < current_day:
        return "unknown"
    return "future"


def should_rollover(current_day: date, observed_day: date) -> bool:
    return observed_day > current_day


def daily_plan_path(workspace_root: Path, target_day: date) -> Path:
    return Path(workspace_root) / "study-plans" / "daily" / f"{target_day.isoformat()}.md"


def reminder_marker_path(workspace_root: Path, current_date: date) -> Path:
    return Path(workspace_root) / "study-lock" / "runtime" / f"reminder-{current_date.isoformat()}.marker"


def should_show_daily_reminder(marker: Path) -> bool:
    return not Path(marker).is_file()


def mark_daily_reminder_shown(marker: Path) -> None:
    marker = Path(marker)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("daily reminder shown\n", encoding="utf-8")


def configure_ui_style(root: tk.Misc) -> ttk.Style:
    root.configure(background=UI_COLORS["background"])
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("App.TFrame", background=UI_COLORS["background"])
    style.configure("Card.TFrame", background=UI_COLORS["surface"])
    style.configure("TLabel", background=UI_COLORS["background"], foreground=UI_COLORS["text"], font=("Microsoft YaHei UI", 10))
    style.configure("Body.TLabel", background=UI_COLORS["surface"], foreground=UI_COLORS["text"], font=("Microsoft YaHei UI", 10))
    style.configure("Muted.TLabel", background=UI_COLORS["surface"], foreground=UI_COLORS["muted"], font=("Microsoft YaHei UI", 9))
    style.configure("NoticeBody.TLabel", background=UI_COLORS["amber_soft"], foreground=UI_COLORS["text"], font=("Microsoft YaHei UI", 10))
    style.configure("Title.TLabel", background=UI_COLORS["background"], foreground=UI_COLORS["primary_dark"], font=("Microsoft YaHei UI", 24, "bold"))
    style.configure("Subtitle.TLabel", background=UI_COLORS["background"], foreground=UI_COLORS["muted"], font=("Microsoft YaHei UI", 10))
    style.configure("CardTitle.TLabel", background=UI_COLORS["surface"], foreground=UI_COLORS["primary_dark"], font=("Microsoft YaHei UI", 14, "bold"))
    style.configure("Section.TLabel", background=UI_COLORS["surface"], foreground=UI_COLORS["primary_dark"], font=("Microsoft YaHei UI", 11, "bold"))
    style.configure("Card.TCheckbutton", background=UI_COLORS["surface"], foreground=UI_COLORS["text"], font=("Microsoft YaHei UI", 10))
    style.map("Card.TCheckbutton", background=[("active", UI_COLORS["blue_soft"])])
    style.configure("Card.TLabelframe", background=UI_COLORS["surface"], bordercolor=UI_COLORS["border"], relief="solid", borderwidth=1)
    style.configure("Card.TLabelframe.Label", background=UI_COLORS["surface"], foreground=UI_COLORS["primary_dark"], font=("Microsoft YaHei UI", 12, "bold"))
    style.configure("Notice.TLabelframe", background=UI_COLORS["amber_soft"], bordercolor="#F0D7A8", relief="solid", borderwidth=1)
    style.configure("Notice.TLabelframe.Label", background=UI_COLORS["amber_soft"], foreground=UI_COLORS["amber"], font=("Microsoft YaHei UI", 11, "bold"))
    style.configure("Notice.TLabel", background=UI_COLORS["amber_soft"], foreground="#8A5A15", font=("Microsoft YaHei UI", 10))
    style.configure("Primary.TButton", background=UI_COLORS["primary"], foreground="#FFFFFF", bordercolor=UI_COLORS["primary"], padding=(13, 8), font=("Microsoft YaHei UI", 10, "bold"))
    style.map("Primary.TButton", background=[("active", "#1E6FCC"), ("disabled", UI_COLORS["disabled"])])
    style.configure("Secondary.TButton", background=UI_COLORS["surface"], foreground=UI_COLORS["primary_dark"], bordercolor=UI_COLORS["border"], padding=(12, 7), font=("Microsoft YaHei UI", 10))
    style.map("Secondary.TButton", background=[("active", UI_COLORS["blue_soft"])])
    style.configure("Small.TButton", background=UI_COLORS["surface"], foreground=UI_COLORS["primary"], bordercolor=UI_COLORS["border"], padding=(8, 5), font=("Microsoft YaHei UI", 9))
    style.map("Small.TButton", background=[("active", UI_COLORS["blue_soft"])])
    style.configure("App.TNotebook", background=UI_COLORS["background"], borderwidth=0)
    style.configure("App.TNotebook.Tab", background=UI_COLORS["background"], foreground=UI_COLORS["muted"], padding=(16, 9), font=("Microsoft YaHei UI", 10))
    style.map("App.TNotebook.Tab", background=[("selected", UI_COLORS["surface"])], foreground=[("selected", UI_COLORS["primary"])])
    style.configure("Card.Horizontal.TProgressbar", troughcolor="#E7EEF6", background=UI_COLORS["primary"], bordercolor="#E7EEF6", lightcolor=UI_COLORS["primary"], darkcolor=UI_COLORS["primary"], thickness=8)
    style.configure("Success.Horizontal.TProgressbar", troughcolor="#E7F1ED", background=UI_COLORS["green"], bordercolor="#E7F1ED", lightcolor=UI_COLORS["green"], darkcolor=UI_COLORS["green"], thickness=8)
    return style


@dataclass(frozen=True)
class TemporaryOverrides:
    apps: set[str]
    domains: set[str]


def can_close_panel(*, enforce: bool, locked: bool) -> bool:
    return not (enforce and locked)


def group_resources(resources: list[LearningResource]) -> dict[str, list[LearningResource]]:
    grouped: dict[str, list[LearningResource]] = {}
    for resource in resources:
        grouped.setdefault(resource.kind, []).append(resource)
    return grouped


def resolve_application_name(
    selection: str | Path,
    *,
    shortcut_resolver: Callable[[Path], Path] | None = None,
) -> str:
    path = Path(selection)
    if path.suffix.lower() == ".exe":
        return path.name.lower()
    if path.suffix.lower() != ".lnk":
        raise ValueError("请选择 .exe 或 .lnk 应用文件")
    if shortcut_resolver is not None:
        target = shortcut_resolver(path)
    else:
        escaped = str(path).replace("'", "''")
        script = "$shell=New-Object -ComObject WScript.Shell; " f"$shell.CreateShortcut('{escaped}').TargetPath"
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            check=False,
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),  # 中文Windows为cp936，UTF-8解码会乱码
            errors="replace",
        )
        if result.returncode != 0:
            raise ValueError("无法读取快捷方式目标")
        target = Path(result.stdout.strip())
    if target.suffix.lower() != ".exe":
        raise ValueError("快捷方式没有指向可执行程序")
    return target.name.lower()


def _override_path(runtime_root: Path, current_date: date) -> Path:
    return Path(runtime_root) / f"overrides-{current_date.isoformat()}.json"


def load_overrides(runtime_root: Path, current_date: date) -> TemporaryOverrides:
    path = _override_path(runtime_root, current_date)
    if not path.is_file():
        return TemporaryOverrides(set(), set())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TemporaryOverrides(
            {str(item).lower() for item in payload.get("apps", [])},
            {normalize_domain(str(item)) for item in payload.get("domains", [])},
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return TemporaryOverrides(set(), set())


def _save_overrides(runtime_root: Path, current_date: date, overrides: TemporaryOverrides) -> None:
    path = _override_path(runtime_root, current_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"apps": sorted(overrides.apps), "domains": sorted(overrides.domains)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def add_temporary_app(runtime_root: Path, current_date: date, executable: str) -> TemporaryOverrides:
    executable = executable.strip().lower()
    if not executable or "/" in executable or "\\" in executable:
        raise ValueError("应用名必须是 exe 文件名，例如 chrome.exe")
    current = load_overrides(runtime_root, current_date)
    updated = TemporaryOverrides(current.apps | {executable}, current.domains)
    _save_overrides(runtime_root, current_date, updated)
    return updated


def add_temporary_domain(runtime_root: Path, current_date: date, domain: str) -> TemporaryOverrides:
    normalized = normalize_domain(domain)
    current = load_overrides(runtime_root, current_date)
    updated = TemporaryOverrides(current.apps, current.domains | {normalized})
    _save_overrides(runtime_root, current_date, updated)
    return updated


class RecordEditor:
    def __init__(self, parent: tk.Misc, record_path: Path) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title(f"学习成果 - {record_path.name}")
        self.window.geometry("820x680")
        self.window.minsize(600, 460)
        self.record_path = Path(record_path)
        self.status_var = tk.StringVar(value="已打开，编辑内容会自动保存")
        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="当天学习成果", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(frame, text=str(self.record_path), foreground="#657184").pack(anchor="w", pady=(3, 8))
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(text_frame, wrap="word", undo=True, font=("Consolas", 11), padx=10, pady=10)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.text.insert("1.0", self.record_path.read_text(encoding="utf-8"))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="left")
        ttk.Button(actions, text="立即保存", command=self._save).pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="保存并关闭", command=self._close).pack(side="right")
        self.window.bind("<Control-s>", lambda _event: self._save())
        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self._autosave_id = self.window.after(1500, self._autosave)

    def _save(self) -> None:
        try:
            save_record(self.record_path, self.text.get("1.0", "end-1c"))
            self.status_var.set(f"已保存 {time.strftime('%H:%M:%S')}")
        except OSError as exc:
            self.status_var.set(f"保存失败：{exc}")

    def _autosave(self) -> None:
        if self.window.winfo_exists():
            self._save()
            self._autosave_id = self.window.after(1500, self._autosave)

    def _close(self) -> None:
        self.window.after_cancel(self._autosave_id)
        self._save()
        self.window.destroy()


class PlanEditor:
    def __init__(self, parent: tk.Misc, workspace_root: Path, initial_date: date) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("计划中心")
        self.window.geometry("900x720")
        self.window.minsize(680, 520)
        self.workspace_root = Path(workspace_root)
        self.date_var = tk.StringVar(value=initial_date.isoformat())
        self.title_var = tk.StringVar(value="学习计划")
        self.status_var = tk.StringVar(value="可以先编辑明日计划，再保存")
        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="计划中心", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(frame, text="编辑日期、步骤、资源和项目流程，保存后主界面会直接显示。", foreground="#657184").pack(anchor="w", pady=(3, 10))
        fields = ttk.Frame(frame)
        fields.pack(fill="x")
        ttk.Label(fields, text="日期").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(fields, textvariable=self.date_var, width=14).grid(row=0, column=1, sticky="w")
        ttk.Label(fields, text="标题").grid(row=0, column=2, sticky="w", padx=(18, 6))
        ttk.Entry(fields, textvariable=self.title_var).grid(row=0, column=3, sticky="ew")
        fields.columnconfigure(3, weight=1)
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.text = tk.Text(text_frame, wrap="word", undo=True, font=("Consolas", 10), padx=10, pady=10)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._load_initial(initial_date)
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="left")
        ttk.Button(actions, text="载入模板", command=self._load_template).pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="保存计划", command=self._save).pack(side="right")

    def _plan_path(self, target: date) -> Path:
        return self.workspace_root / "study-plans" / "daily" / f"{target.isoformat()}.md"

    def _load_initial(self, target: date) -> None:
        path = self._plan_path(target)
        if path.is_file():
            self.text.insert("1.0", path.read_text(encoding="utf-8"))
        else:
            self._load_template()

    def _load_template(self) -> None:
        try:
            target = date.fromisoformat(self.date_var.get().strip())
        except ValueError:
            self.status_var.set("日期格式应为 YYYY-MM-DD")
            return
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", detailed_plan_template(target, title=self.title_var.get().strip() or "学习计划"))
        self.status_var.set("模板已载入，可以继续改成自己的步骤")

    def _save(self) -> None:
        try:
            target = date.fromisoformat(self.date_var.get().strip())
            content = sync_plan_date_heading(self.text.get("1.0", "end-1c"), target)
            path = save_plan(self.workspace_root, target, content)
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", content)
            self.status_var.set(f"已保存：{path.name}（日期已同步）")
        except (OSError, ValueError) as exc:
            messagebox.showwarning("计划无法保存", str(exc), parent=self.window)


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, height: int = 360) -> None:
        super().__init__(parent, style="Card.TFrame")
        self.canvas = tk.Canvas(self, background=UI_COLORS["surface"], highlightthickness=0, height=height)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="Card.TFrame")
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resize_inner)
        self.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.bind_all("<Button-4>", self._on_mousewheel, add="+")
        self.bind_all("<Button-5>", self._on_mousewheel, add="+")

    def _resize_inner(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root) or event.widget
        current = widget
        while current is not None and not isinstance(current, ScrollableFrame):
            current = getattr(current, "master", None)
        if current is not self:
            return
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            units = wheel_scroll_units(getattr(event, "delta", 0)) * 3
        if units:
            self.canvas.yview_scroll(units, "units")


class LearningCockpit:
    def __init__(
        self,
        parent: tk.Misc,
        plan: DailyPlan,
        plan_path: Path,
        workspace_root: Path,
        *,
        url_opener: Callable[[str], object] | None = None,
        file_opener: Callable[[Path], object] | None = None,
        readonly: bool = False,
        on_status: Callable[[str], object] | None = None,
        on_progress: Callable[[int, int], object] | None = None,
    ) -> None:
        self.parent = parent
        self.plan = plan
        self.plan_path = Path(plan_path)
        self.workspace_root = Path(workspace_root)
        self.url_opener = url_opener
        self.file_opener = file_opener
        self.readonly = readonly
        self.on_status = on_status
        self.on_progress = on_progress
        self.step_vars: list[tk.BooleanVar] = []
        self.step_views: list[tuple[tk.Frame, tk.Label, tk.Label, tk.Label | None]] = []
        self.step_extra_labels: list[list[tk.Label]] = []
        self.frame = ttk.Frame(parent)
        self.status_var = tk.StringVar(value="资源已准备")

    def build(self) -> ttk.Frame:
        self.frame.pack(fill="both", expand=True)
        self.frame.configure(style="App.TFrame")
        self.frame.columnconfigure(0, weight=3)
        self.frame.columnconfigure(1, weight=2)
        self.frame.rowconfigure(1, weight=1)

        goal = ttk.LabelFrame(self.frame, text="今日完成标准", style="Card.TLabelframe", padding=(12, 8))
        goal.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(goal, text=self.plan.goal or "当前计划还没有填写今日目标。", style="Body.TLabel", wraplength=1000, justify="left").pack(anchor="w", padx=14, pady=13)

        workflow_box = ttk.LabelFrame(self.frame, text="今天按这个顺序完成", style="Card.TLabelframe", padding=(8, 6))
        workflow_box.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        workflow_box.columnconfigure(0, weight=1)
        header = ttk.Frame(workflow_box, style="Card.TFrame")
        header.pack(fill="x", padx=14, pady=(12, 0))
        ttk.Label(header, text="每一步都有对应资料、时间预算和可检查产物", style="Muted.TLabel").pack(side="left")
        self.progress_var = tk.StringVar()
        self.progress_label = ttk.Label(header, textvariable=self.progress_var, style="Muted.TLabel")
        self.progress_label.pack(side="right")
        self.progress_bar = ttk.Progressbar(workflow_box, style="Card.Horizontal.TProgressbar", maximum=100)
        self.progress_bar.pack(fill="x", padx=14, pady=(8, 10))
        steps = self.plan.workflow or self.plan.tasks
        self.steps = steps
        if not steps:
            ttk.Label(workflow_box, text="还没有执行步骤，请在计划中心补充。", style="Body.TLabel").pack(anchor="w", padx=14, pady=12)
        else:
            scroll = ScrollableFrame(workflow_box, height=360)
            scroll.pack(fill="both", expand=True, padx=4, pady=(0, 4))
            for index, task in enumerate(steps, start=1):
                self._step_row(scroll.inner, index, task)
        self._update_progress()

        resources_box = ttk.LabelFrame(self.frame, text="今日资料包", style="Card.TLabelframe", padding=(4, 4))
        resources_box.grid(row=1, column=1, sticky="nsew")
        resources_box.columnconfigure(0, weight=1)
        scroll = ScrollableFrame(resources_box, height=420)
        scroll.pack(fill="both", expand=True, padx=6, pady=6)
        grouped = group_resources(self.plan.resources)
        if not grouped:
            ttk.Label(scroll.inner, text="当前计划还没有配置资料包。", style="Body.TLabel").pack(anchor="w", padx=10, pady=12)
        else:
            for kind, resources in grouped.items():
                ttk.Label(scroll.inner, text=kind, style="Section.TLabel").pack(anchor="w", padx=10, pady=(8, 4))
                for resource in resources:
                    self._resource_row(scroll.inner, resource)
        ttk.Button(resources_box, text="打开今日资料包", style="Primary.TButton", command=self._open_all).pack(anchor="w", padx=12, pady=(2, 12))

        project_box = ttk.LabelFrame(self.frame, text="项目流程", style="Card.TLabelframe", padding=(10, 6))
        project_box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        milestones = self.plan.project_milestones
        if not milestones:
            ttk.Label(project_box, text="当前计划还没有项目里程碑。", style="Body.TLabel").pack(anchor="w", padx=14, pady=10)
        else:
            for index, milestone in enumerate(milestones, start=1):
                color = UI_COLORS["green"] if milestone.completed else UI_COLORS["primary"]
                label = tk.Label(project_box, text=f"{'✓' if milestone.completed else '○'}  {index}. {milestone.label}", bg=UI_COLORS["surface"], fg=color, anchor="w", font=("Microsoft YaHei UI", 10))
                label.pack(fill="x", padx=14, pady=3)
        ttk.Label(project_box, textvariable=self.status_var, style="Muted.TLabel").pack(anchor="w", padx=14, pady=(6, 10))
        return self.frame

    def _step_row(self, parent: ttk.Frame, index: int, task) -> None:
        is_current = not task.completed and all(item.completed for item in self.steps[: index - 1])
        background = UI_COLORS["green_soft"] if task.completed else UI_COLORS["blue_soft"] if is_current else UI_COLORS["surface"]
        row = tk.Frame(parent, bg=background, highlightbackground=UI_COLORS["border"], highlightthickness=1)
        row.pack(fill="x", padx=10, pady=3)
        row.columnconfigure(1, weight=1)
        badge_color = UI_COLORS["green"] if task.completed else UI_COLORS["primary"]
        badge = tk.Label(row, text="✓" if task.completed else str(index), bg=badge_color, fg="#FFFFFF", width=3, height=1, font=("Microsoft YaHei UI", 10, "bold"))
        badge.grid(row=0, column=0, padx=(3, 10), pady=8, sticky="n")
        text_frame = tk.Frame(row, bg=background)
        text_frame.grid(row=0, column=1, sticky="ew", pady=5)
        title = task.label.split("：", 1)[0] if "：" in task.label else task.label
        detail = task.label.split("：", 1)[1] if "：" in task.label else ""
        title_label = tk.Label(text_frame, text=title, bg=background, fg=UI_COLORS["primary_dark"], anchor="w", justify="left", wraplength=650, font=("Microsoft YaHei UI", 10, "bold" if not task.completed else "normal"))
        title_label.pack(fill="x")
        detail_label = None
        if detail:
            detail_label = tk.Label(text_frame, text=detail, bg=background, fg=UI_COLORS["muted"], anchor="w", justify="left", wraplength=650, font=("Microsoft YaHei UI", 9))
            detail_label.pack(fill="x", pady=(2, 0))
        resource = self.plan.resources[index - 1] if index <= len(self.plan.resources) else None
        extra_labels: list[tk.Label] = []
        if resource is not None:
            resource_label = tk.Label(text_frame, text=f"资料 · {resource.title}", bg=background, fg=UI_COLORS["primary"], anchor="w", justify="left", wraplength=650, font=("Microsoft YaHei UI", 9, "bold"))
            resource_label.pack(fill="x", pady=(3, 0))
            extra_labels.append(resource_label)
        if resource is not None and resource.output:
            output_label = tk.Label(text_frame, text=f"产出 · {resource.output}", bg=background, fg=UI_COLORS["green"], anchor="w", justify="left", wraplength=650, font=("Microsoft YaHei UI", 9, "bold"))
            output_label.pack(fill="x", pady=(3, 0))
            extra_labels.append(output_label)
        variable = tk.BooleanVar(value=task.completed)
        self.step_vars.append(variable)
        check = tk.Checkbutton(row, text="完成", variable=variable, command=lambda item=task, value=variable: self._toggle_step(item, value), bg=background, fg=UI_COLORS["text"], activebackground=background, activeforeground=UI_COLORS["primary_dark"], selectcolor=background, highlightthickness=0, bd=0, font=("Microsoft YaHei UI", 9), state=tk.DISABLED if self.readonly else tk.NORMAL)
        if resource is not None:
            ttk.Button(row, text="打开资料", style="Primary.TButton", command=lambda item=resource: self._open_one(item)).grid(row=0, column=2, padx=(4, 6), pady=8, sticky="ne")
        check.grid(row=0, column=3, padx=(8, 3), pady=8, sticky="ne")
        self.step_views.append((row, badge, title_label, detail_label))
        self.step_extra_labels.append(extra_labels)

    def _resource_row(self, parent: ttk.Frame, resource: LearningResource) -> None:
        row = tk.Frame(parent, bg=UI_COLORS["surface"], highlightbackground=UI_COLORS["border"], highlightthickness=1)
        row.pack(fill="x", padx=8, pady=4)
        body = tk.Frame(row, bg=UI_COLORS["surface"])
        body.pack(side="left", fill="x", expand=True, padx=10, pady=8)
        tk.Label(body, text=resource.title, bg=UI_COLORS["surface"], fg=UI_COLORS["primary_dark"], anchor="w", justify="left", wraplength=330, font=("Microsoft YaHei UI", 9, "bold")).pack(fill="x")
        if resource.purpose:
            tk.Label(body, text=resource.purpose, bg=UI_COLORS["surface"], fg=UI_COLORS["muted"], anchor="w", justify="left", wraplength=330, font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(2, 0))
        if resource.output:
            tk.Label(body, text=f"产出：{resource.output}", bg=UI_COLORS["surface"], fg=UI_COLORS["green"], anchor="w", justify="left", wraplength=330, font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(2, 0))
        ttk.Button(row, text="打开", style="Small.TButton", command=lambda item=resource: self._open_one(item)).pack(side="right", padx=8, pady=8)

    def _toggle_step(self, task, variable: tk.BooleanVar) -> None:
        if self.readonly:
            return
        section = "执行流程" if self.plan.workflow else "任务"
        try:
            write_section_checkbox_state(self.plan_path, section, task.task_id, variable.get())
            task.completed = variable.get()
            self._set_status("步骤状态已保存")
            self._update_progress()
            self._refresh_step_views()
        except (OSError, ValueError, RuntimeError) as exc:
            variable.set(task.completed)
            self._set_status(f"步骤保存失败：{exc}")

    def _update_progress(self) -> None:
        completed = sum(task.completed for task in self.steps)
        total = len(self.steps)
        percent = progress_percent(completed, total)
        self.progress_var.set(progress_text(completed, total))
        self.progress_bar["value"] = percent
        self.progress_bar.configure(style="Success.Horizontal.TProgressbar" if percent == 100 else "Card.Horizontal.TProgressbar")
        if self.on_progress is not None:
            self.on_progress(completed, total)

    def _refresh_step_views(self) -> None:
        first_open = next((index for index, task in enumerate(self.steps) if not task.completed), len(self.steps))
        for index, (row, badge, title_label, detail_label) in enumerate(self.step_views):
            task = self.steps[index]
            is_current = index == first_open
            background = UI_COLORS["green_soft"] if task.completed else UI_COLORS["blue_soft"] if is_current else UI_COLORS["surface"]
            row.configure(bg=background)
            badge.configure(bg=UI_COLORS["green"] if task.completed else UI_COLORS["primary"])
            title_label.configure(bg=background, font=("Microsoft YaHei UI", 10, "normal" if task.completed else "bold"))
            if detail_label is not None:
                detail_label.configure(bg=background)
            for label in self.step_extra_labels[index]:
                label.configure(bg=background)

    def _open_one(self, resource: LearningResource) -> None:
        result = open_resource(self.workspace_root, resource, file_opener=self.file_opener, url_opener=self.url_opener)
        self._set_status(result.message)

    def _open_all(self) -> None:
        failures: list[str] = []
        for resource in self.plan.resources:
            result = open_resource(self.workspace_root, resource, file_opener=self.file_opener, url_opener=self.url_opener)
            if not result.ok:
                failures.append(result.message)
        self._set_status("全部资料已打开" if not failures else "；".join(failures[:2]))

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)
        if self.on_status is not None:
            self.on_status(message)


def build_project_tab(
    parent: tk.Misc,
    plan: DailyPlan,
    *,
    on_open_resource: Callable[[LearningResource], object] | None = None,
) -> None:
    parent.configure(style="App.TFrame")
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(1, weight=1)
    intro = ttk.LabelFrame(parent, text="项目路线", style="Card.TLabelframe", padding=(16, 12))
    intro.grid(row=0, column=0, sticky="ew", pady=(0, 14))
    ttk.Label(intro, text="把论文阅读转成可复现、可展示、可继续迭代的工业视觉项目。", style="CardTitle.TLabel").pack(anchor="w")
    ttk.Label(intro, text=plan.goal or "今天先完成一个可运行的基线，再留下下一步可验证的改进假设。", style="Body.TLabel", wraplength=1050, justify="left").pack(anchor="w", pady=(6, 0))

    box = ttk.LabelFrame(parent, text="里程碑清单", style="Card.TLabelframe", padding=(12, 10))
    box.grid(row=1, column=0, sticky="nsew")
    box.columnconfigure(0, weight=1)
    milestones = plan.project_milestones
    if not milestones:
        ttk.Label(box, text="当前计划还没有项目里程碑，请在明日计划中补充。", style="Body.TLabel").pack(anchor="w", padx=8, pady=12)
    else:
        for index, milestone in enumerate(milestones, start=1):
            background = UI_COLORS["green_soft"] if milestone.completed else UI_COLORS["surface"]
            row = tk.Frame(box, bg=background, highlightbackground=UI_COLORS["border"], highlightthickness=1)
            row.pack(fill="x", padx=4, pady=4)
            badge = tk.Label(row, text="✓" if milestone.completed else str(index), bg=UI_COLORS["green"] if milestone.completed else UI_COLORS["primary"], fg="#FFFFFF", width=3, font=("Microsoft YaHei UI", 10, "bold"))
            badge.pack(side="left", padx=(10, 10), pady=10)
            text_frame = tk.Frame(row, bg=background)
            text_frame.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=8)
            tk.Label(text_frame, text=milestone.label, bg=background, fg=UI_COLORS["primary_dark"], anchor="w", justify="left", wraplength=850, font=("Microsoft YaHei UI", 10, "bold" if not milestone.completed else "normal")).pack(fill="x")
            if milestone.detail:
                tk.Label(text_frame, text=milestone.detail, bg=background, fg=UI_COLORS["muted"], anchor="w", justify="left", wraplength=850, font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(3, 0))

    project_resource = next((item for item in plan.resources if item.kind == "项目"), None)
    if project_resource is not None and on_open_resource is not None:
        ttk.Button(parent, text="打开项目工作区", style="Primary.TButton", command=lambda: on_open_resource(project_resource)).grid(row=2, column=0, sticky="w", pady=(14, 0))


def build_tomorrow_tab(
    parent: tk.Misc,
    workspace_root: Path,
    target: date,
    *,
    on_edit: Callable[[], object],
) -> None:
    parent.configure(style="App.TFrame")
    parent.columnconfigure(0, weight=1)
    path = Path(workspace_root) / "study-plans" / "daily" / f"{target.isoformat()}.md"
    card = ttk.LabelFrame(parent, text=f"{target.isoformat()} · 明日学习计划", style="Card.TLabelframe", padding=(16, 14))
    card.grid(row=0, column=0, sticky="ew")
    if path.is_file():
        try:
            plan = parse_plan(path)
        except (OSError, ValueError) as exc:
            ttk.Label(card, text=f"计划暂时无法读取：{exc}", style="Body.TLabel", wraplength=1000).pack(anchor="w")
        else:
            steps = plan.workflow or plan.tasks
            ttk.Label(card, text=plan.title, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text=plan.goal or "明日目标尚未填写。", style="Body.TLabel", wraplength=1050, justify="left").pack(anchor="w", pady=(7, 0))
            summary = f"{len(steps)} 个执行步骤  ·  {len(plan.resources)} 项资料  ·  {len(plan.project_milestones)} 个项目里程碑"
            ttk.Label(card, text=summary, style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
            ttk.Separator(card).pack(fill="x", pady=(12, 8))
            for index, task in enumerate(steps[:8], start=1):
                ttk.Label(card, text=f"{index:02d}  {task.label}", style="Body.TLabel", wraplength=1050, justify="left").pack(anchor="w", pady=2)
    else:
        ttk.Label(card, text="还没有明日计划。", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, text="先安排好明天的步骤、资料和项目产出，打开软件后就能直接进入学习。", style="Body.TLabel", wraplength=1050).pack(anchor="w", pady=(7, 0))
    ttk.Button(parent, text="编辑明日计划", style="Primary.TButton", command=on_edit).grid(row=1, column=0, sticky="w", pady=(14, 0))


class FocusTimerPanel:
    def __init__(self, parent: tk.Misc, plan: DailyPlan, *, on_focus_seconds: Callable[[float], object] | None = None) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Study Lock · 专注计时器")
        self.window.geometry("560x360")
        self.window.minsize(500, 320)
        self.window.transient(parent)
        self.stages = build_focus_stages(plan.workflow or plan.tasks)
        self.state = initial_timer_state(self.stages)
        self.on_focus_seconds = on_focus_seconds
        self._last_focus_tick: float | None = None
        self.tick_job: str | None = None
        self.stage_var = tk.StringVar()
        self.time_var = tk.StringVar()
        self.status_var = tk.StringVar(value="准备开始")
        frame = ttk.Frame(self.window, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="专注计时器", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text="按今日步骤自动切换阶段，完成后仍需在今日计划中勾选步骤。", style="Muted.TLabel", wraplength=480).pack(anchor="w", pady=(5, 18))
        ttk.Label(frame, textvariable=self.stage_var, style="Section.TLabel").pack(anchor="center")
        ttk.Label(frame, textvariable=self.time_var, font=("Segoe UI", 42, "bold"), foreground=UI_COLORS["primary_dark"]).pack(anchor="center", pady=(8, 4))
        ttk.Label(frame, textvariable=self.status_var, style="Muted.TLabel").pack(anchor="center")
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(22, 0))
        self.start_button = ttk.Button(actions, text="开始", style="Primary.TButton", command=self._start)
        self.start_button.pack(side="left", padx=(0, 8))
        self.pause_button = ttk.Button(actions, text="暂停", style="Secondary.TButton", command=self._pause)
        self.pause_button.pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="重置", style="Secondary.TButton", command=self._reset).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="跳过当前阶段", style="Secondary.TButton", command=self._skip).pack(side="left")
        ttk.Button(actions, text="关闭", style="Secondary.TButton", command=self.close).pack(side="right")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._refresh()

    def _refresh(self) -> None:
        stage = self.stages[self.state.stage_index]
        self.stage_var.set(f"阶段 {self.state.stage_index + 1} / {len(self.stages)} · {stage.label}")
        self.time_var.set(format_remaining(self.state.remaining_seconds))
        self.start_button.configure(state="disabled" if self.state.running else "normal")
        self.pause_button.configure(state="normal" if self.state.running else "disabled")

    def _start(self) -> None:
        self.state = start_timer(self.state)
        self._last_focus_tick = time.monotonic()
        self.status_var.set("专注进行中")
        self._refresh()
        self._schedule_tick()

    def _pause(self) -> None:
        self._record_elapsed()
        self.state = pause_timer(self.state)
        self.status_var.set("已暂停")
        self._cancel_tick()
        self._refresh()

    def _reset(self) -> None:
        self._record_elapsed()
        self._cancel_tick()
        self.state = reset_timer(self.stages)
        self.status_var.set("已重置")
        self._refresh()

    def _skip(self) -> None:
        self._record_elapsed()
        self._cancel_tick()
        if self.state.stage_index + 1 >= len(self.stages):
            self.state = TimerState(self.state.stage_index, 0, False)
            self.status_var.set("全部阶段结束")
        else:
            next_index = self.state.stage_index + 1
            self.state = TimerState(next_index, self.stages[next_index].seconds, self.state.running)
            self.status_var.set("已进入下一阶段")
            if self.state.running:
                self._schedule_tick()
        self._refresh()

    def _schedule_tick(self) -> None:
        self._cancel_tick()
        if self.state.running:
            self.tick_job = self.window.after(1000, self._tick)

    def _tick(self) -> None:
        self.tick_job = None
        self._record_elapsed()
        self.state, finished = tick_timer(self.state, self.stages)
        self._refresh()
        if finished:
            self.window.bell()
            self.status_var.set("上一阶段完成，已自动进入下一阶段" if self.state.running else "全部阶段完成")
        self._schedule_tick()

    def _cancel_tick(self) -> None:
        if self.tick_job is not None:
            self.window.after_cancel(self.tick_job)
            self.tick_job = None

    def close(self) -> None:
        self._record_elapsed()
        self.state = pause_timer(self.state)
        self._cancel_tick()
        if self.window.winfo_exists():
            self.window.destroy()

    def _record_elapsed(self) -> None:
        now = time.monotonic()
        previous = self._last_focus_tick
        self._last_focus_tick = now if self.state.running else None
        if previous is None or not self.state.running or self.on_focus_seconds is None:
            return
        seconds = min(max(0.0, now - previous), float(self.state.remaining_seconds))
        if seconds > 0:
            try:
                self.on_focus_seconds(seconds)
            except (OSError, ValueError) as exc:
                self.status_var.set(f"专注时长保存失败：{exc}")


class CheckinCalendarPanel:
    def __init__(self, parent: tk.Misc, workspace_root: Path, current_day: date) -> None:
        self.workspace_root = Path(workspace_root)
        self.current_day = current_day
        self.year = current_day.year
        self.month = current_day.month
        self.window = tk.Toplevel(parent)
        self.window.title("Study Lock · 打卡日历")
        self.window.geometry("620x560")
        self.window.minsize(560, 500)
        self.window.transient(parent)
        self.body = ttk.Frame(self.window, padding=18)
        self.body.pack(fill="both", expand=True)
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)
        self._refresh()

    def _month_progress(self) -> dict[date, DailyProgress]:
        result: dict[date, DailyProgress] = {}
        for path in (self.workspace_root / "study-lock" / "runtime").glob("progress-*.json"):
            try:
                day = date.fromisoformat(path.stem.removeprefix("progress-"))
            except ValueError:
                continue
            result[day] = load_daily_progress(self.workspace_root, day)
        return result

    def _refresh(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        history = self._month_progress()
        stats = streak_stats(history, self.current_day)
        header = ttk.Frame(self.body)
        header.pack(fill="x")
        ttk.Button(header, text="‹", style="Secondary.TButton", width=3, command=lambda: self._move_month(-1)).pack(side="left")
        ttk.Label(header, text=f"{self.year} 年 {self.month} 月", style="CardTitle.TLabel").pack(side="left", expand=True)
        ttk.Button(header, text="›", style="Secondary.TButton", width=3, command=lambda: self._move_month(1)).pack(side="right")
        ttk.Label(self.body, text=f"当前连胜 {stats['current']} 天　最长连胜 {stats['longest']} 天　累计打卡 {stats['completed_days']} 天", style="Muted.TLabel").pack(anchor="w", pady=(8, 16))
        grid = ttk.Frame(self.body)
        grid.pack(fill="both", expand=True)
        for column, label in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            ttk.Label(grid, text=label, style="Section.TLabel", anchor="center").grid(row=0, column=column, sticky="ew", pady=(0, 8))
            grid.columnconfigure(column, weight=1)
        for row, week in enumerate(calendar.monthcalendar(self.year, self.month), start=1):
            grid.rowconfigure(row, weight=1)
            for column, number in enumerate(week):
                if not number:
                    ttk.Label(grid, text="", style="App.TFrame").grid(row=row, column=column, sticky="nsew", padx=3, pady=3)
                    continue
                day = date(self.year, self.month, number)
                progress = history.get(day)
                state = calendar_day_state(day, self.current_day, progress)
                if state == "checked":
                    background, foreground, mark = UI_COLORS["green_soft"], UI_COLORS["green"], "✓"
                elif state == "missed":
                    background, foreground, mark = UI_COLORS["amber_soft"], UI_COLORS["amber"], "·"
                else:
                    background, foreground, mark = UI_COLORS["surface"], UI_COLORS["muted"], ""
                if state == "today":
                    background = UI_COLORS["blue_soft"]
                tk.Label(grid, text=f"{number}\n{mark}", bg=background, fg=foreground, font=("Microsoft YaHei UI", 10, "bold"), relief="solid", bd=1).grid(row=row, column=column, sticky="nsew", padx=3, pady=3)
        ttk.Label(self.body, text="绿色 = 已打卡　橙色 = 过去未打卡　蓝色 = 今天", style="Muted.TLabel").pack(anchor="w", pady=(14, 0))

    def _move_month(self, offset: int) -> None:
        month = self.month + offset
        year = self.year
        if month < 1:
            year, month = year - 1, 12
        elif month > 12:
            year, month = year + 1, 1
        self.year, self.month = year, month
        self._refresh()


class StudyPanel:
    def __init__(
        self,
        root: tk.Tk,
        plan: DailyPlan,
        plan_path: Path,
        workspace_root: Path,
        *,
        current_date: date | None = None,
        browser_status: str | None = None,
        on_overrides_changed: Callable[[], object] | None = None,
        on_unlock: Callable[[], object] | None = None,
        on_recovery: Callable[[str, RecoveryGate], object] | None = None,
        url_opener: Callable[[str], object] | None = None,
        file_opener: Callable[[Path], object] | None = None,
        enforce_close_guard: bool = False,
        mode_label: str = "模拟模式",
        reminder_enabled: bool = False,
        health_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self.root = root
        self.plan = plan
        self.plan_path = Path(plan_path)
        self.workspace_root = Path(workspace_root)
        self.current_date = current_date or date.today()
        self.browser_status = browser_status or "未启动"
        self.on_overrides_changed = on_overrides_changed
        self.on_unlock = on_unlock
        self.on_recovery = on_recovery
        self.url_opener = url_opener
        self.file_opener = file_opener
        self.enforce_close_guard = enforce_close_guard
        self.reminder_enabled = reminder_enabled
        self.health_provider = health_provider
        self._health_job: str | None = None
        self.notification_config = load_pushplus_config(self.workspace_root)
        previous_plan = None
        previous_path = self.workspace_root / "study-plans" / "daily" / f"{(self.current_date - timedelta(days=1)).isoformat()}.md"
        if previous_path.is_file():
            try:
                previous_plan = parse_plan(previous_path)
            except (OSError, ValueError):
                previous_plan = None
        self.daily_progress = prepare_daily_progress(self.workspace_root, self.current_date, self.plan, previous_plan)
        self._focus_timer: FocusTimerPanel | None = None
        self.checkin_button: ttk.Button | None = None
        self.carryover_controls: list[tuple[int, CarryoverTask, tk.Checkbutton]] = []
        self._reminder_job: str | None = None
        self.status_var = tk.StringVar(value=f"LOCKED · {mode_label}")
        if self.reminder_enabled:
            self.status_var.set("提醒模式 · 今天的学习内容已准备")
        self.recovery_gate: RecoveryGate | None = None
        configure_ui_style(self.root)
        self._build()
        self._start_reminders()
        if self.health_provider is not None:
            self._health_job = self.root.after(1000, self._check_health)

    def _check_health(self) -> None:
        self._health_job = None
        error = self.health_provider() if self.health_provider is not None else None
        if error:
            self.enforce_close_guard = False
            self.status_var.set(f"SAFE_CONFIG · 限制已停止：{error}")
            messagebox.showwarning("运行故障：已停止限制", f"{error}\n\n已进入 SAFE_CONFIG，可以关闭窗口并检查配置。", parent=self.root)
            return
        if self.health_provider is not None:
            self._health_job = self.root.after(1000, self._check_health)

    def _build(self) -> None:
        self.root.title("Study Lock · 今日学习内容")
        self.root.geometry("1240x860")
        self.root.minsize(980, 700)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        outer = ttk.Frame(self.root, style="App.TFrame", padding=(28, 24))
        self.outer_frame = outer
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(2, weight=1)
        outer.columnconfigure(0, weight=1)

        header = ttk.Frame(outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        title_frame = ttk.Frame(header, style="App.TFrame")
        title_frame.grid(row=0, column=0, sticky="w")
        ttk.Label(title_frame, text="今日学习内容", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_frame, text=f"{self.current_date.isoformat()} · {self.plan.title} · 论文精读 + 可复现实验 + 项目路线", style="Subtitle.TLabel").pack(anchor="w", pady=(5, 0))
        summary = self.plan.workflow or self.plan.tasks
        self.header_status_var = tk.StringVar(value="提醒模式 · 不干预系统" if self.reminder_enabled else "学习内容已准备")
        self.header_progress_var = tk.StringVar(
            value=combined_progress_text(
                sum(item.completed for item in summary),
                len(summary),
                sum(item.completed for item in self.daily_progress.carryovers),
                len(self.daily_progress.carryovers),
            )
        )
        status_frame = tk.Frame(header, bg=UI_COLORS["background"])
        status_frame.grid(row=0, column=1, sticky="e", padx=(20, 0))
        tk.Label(status_frame, text="●", bg=UI_COLORS["background"], fg=UI_COLORS["green"], font=("Segoe UI", 12)).pack(side="left", padx=(0, 6))
        status_text = tk.Frame(status_frame, bg=UI_COLORS["background"])
        status_text.pack(side="left")
        tk.Label(status_text, textvariable=self.header_status_var, bg=UI_COLORS["background"], fg=UI_COLORS["primary_dark"], font=("Microsoft YaHei UI", 10, "bold"), anchor="e").pack(anchor="e")
        tk.Label(status_text, textvariable=self.header_progress_var, bg=UI_COLORS["background"], fg=UI_COLORS["muted"], font=("Microsoft YaHei UI", 9), anchor="e").pack(anchor="e", pady=(2, 0))

        tabs = ttk.Notebook(outer, style="App.TNotebook")
        tabs.grid(row=2, column=0, sticky="nsew", pady=(20, 12))
        today_tab = ttk.Frame(tabs, style="App.TFrame", padding=(0, 12, 0, 0))
        project_tab = ttk.Frame(tabs, style="App.TFrame", padding=(0, 12, 0, 0))
        tomorrow_tab = ttk.Frame(tabs, style="App.TFrame", padding=(0, 12, 0, 0))
        tabs.add(today_tab, text="今日总览")
        tabs.add(project_tab, text="项目流程")
        tabs.add(tomorrow_tab, text="明日计划")
        today_scroll = ScrollableFrame(today_tab, height=560)
        today_scroll.pack(fill="both", expand=True)
        self._build_carryover_panel(today_scroll.inner)
        cockpit = LearningCockpit(today_scroll.inner, self.plan, self.plan_path, self.workspace_root, url_opener=self.url_opener, file_opener=self.file_opener, on_status=self._set_status, on_progress=self._on_cockpit_progress)
        cockpit.build()
        self.cockpit = cockpit
        build_project_tab(project_tab, self.plan, on_open_resource=self._open_resource)
        build_tomorrow_tab(tomorrow_tab, self.workspace_root, self.current_date + timedelta(days=1), on_edit=self._open_plan_center)
        if not self.reminder_enabled:
            self._build_allowlist(outer)
        actions = ttk.Frame(outer, style="App.TFrame")
        actions.grid(row=3 if self.reminder_enabled else 4, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(actions, textvariable=self.status_var, style="Subtitle.TLabel").pack(side="left", padx=(2, 12))
        ttk.Button(actions, text="记录学习成果", style="Primary.TButton", command=self._open_record).pack(side="left", padx=(0, 8))
        if self.reminder_enabled:
            ttk.Button(actions, text="专注计时器", style="Secondary.TButton", command=self._open_focus_timer).pack(side="left", padx=(0, 8))
            ttk.Button(actions, text="打卡与日历", style="Secondary.TButton", command=lambda: CheckinCalendarPanel(self.root, self.workspace_root, self.current_date)).pack(side="left", padx=(0, 8))
            self.checkin_button = ttk.Button(actions, text="完成今日打卡", style="Primary.TButton", command=self._check_in)
            self.checkin_button.pack(side="left", padx=(0, 8))
            ttk.Button(actions, text="安排明日计划", style="Secondary.TButton", command=self._open_plan_center).pack(side="left")
            ttk.Button(actions, text="微信通知设置", style="Secondary.TButton", command=self._open_notification_settings).pack(side="left", padx=(8, 0))
            ttk.Label(actions, text="完成全部步骤后，小时提醒会自动停止", style="Subtitle.TLabel").pack(side="right")
        else:
            ttk.Button(actions, text="检查解锁", style="Secondary.TButton", command=self._check_unlock).pack(side="left", padx=(0, 8))
            ttk.Button(actions, text="申请解锁", style="Primary.TButton", command=self._request_unlock).pack(side="left")
            ttk.Button(actions, text="紧急恢复", style="Secondary.TButton", command=self._request_recovery).pack(side="right")
        self._update_checkin_state()

    def _open_focus_timer(self) -> None:
        timer = getattr(self, "_focus_timer", None)
        if timer is not None and timer.window.winfo_exists():
            timer.window.deiconify()
            timer.window.lift()
            timer.window.focus_set()
            return
        day = self.current_date
        def record(seconds: float) -> None:
            add_focus_seconds(self.workspace_root, day, seconds)
            if day == self.current_date:
                self.daily_progress.focus_seconds = load_daily_progress(self.workspace_root, day).focus_seconds
        self._focus_timer = FocusTimerPanel(self.root, self.plan, on_focus_seconds=record)

    def _build_carryover_panel(self, parent: tk.Misc) -> None:
        box = ttk.LabelFrame(parent, text="昨日未完成 · 自动顺延", style="Notice.TLabelframe", padding=(12, 8))
        box.pack(fill="x", padx=0, pady=(0, 12))
        if not self.daily_progress.carryovers:
            ttk.Label(box, text="没有需要补做的内容，今天按下面的步骤完成即可。", style="Notice.TLabel").pack(anchor="w")
            return
        ttk.Label(box, text="这些内容来自昨天的未完成步骤；全部勾选后才能完成今日打卡。", style="Notice.TLabel", wraplength=1000).pack(anchor="w", pady=(0, 5))
        for index, item in enumerate(self.daily_progress.carryovers):
            row = tk.Frame(box, bg=UI_COLORS["amber_soft"])
            row.pack(fill="x", pady=2)
            row.columnconfigure(0, weight=1)
            variable = tk.BooleanVar(value=item.completed)
            check = tk.Checkbutton(
                row,
                text=f"补做 · {item.label}",
                variable=variable,
                command=lambda carryover=item, value=variable: self._toggle_carryover(carryover, value),
                bg=UI_COLORS["amber_soft"],
                fg=UI_COLORS["text"],
                activebackground=UI_COLORS["amber_soft"],
                selectcolor=UI_COLORS["amber_soft"],
                highlightthickness=0,
                bd=0,
                anchor="w",
                justify="left",
                wraplength=560,
                font=("Microsoft YaHei UI", 9),
            )
            check.grid(row=0, column=0, sticky="ew", padx=(4, 8), pady=6)
            self.carryover_controls.append((index, item, check))
            if item.resource is not None:
                ttk.Button(row, text="打开资料", style="Primary.TButton", command=lambda resource=item.resource: self._open_carryover_resource(resource)).grid(row=0, column=1, sticky="e", padx=(0, 8), pady=6)

        self._refresh_carryover_controls()

    def _toggle_carryover(self, item: CarryoverTask, variable: tk.BooleanVar) -> None:
        item.completed = variable.get()
        save_daily_progress(self.workspace_root, self.daily_progress)
        self._refresh_carryover_controls()
        self._update_checkin_state()

    def _refresh_carryover_controls(self) -> None:
        for index, item, check in self.carryover_controls:
            state = "disabled" if item.completed or not carryover_is_unlocked(self.daily_progress.carryovers, index) else "normal"
            check.configure(state=state)

    def _open_carryover_resource(self, resource: LearningResource) -> None:
        result = open_resource(self.workspace_root, resource, file_opener=self.file_opener, url_opener=self.url_opener)
        self._set_status(result.message)

    def _load_progress_history(self) -> dict[date, DailyProgress]:
        history: dict[date, DailyProgress] = {}
        runtime = self.workspace_root / "study-lock" / "runtime"
        for path in runtime.glob("progress-*.json"):
            try:
                day = date.fromisoformat(path.stem.removeprefix("progress-"))
            except ValueError:
                continue
            history[day] = load_daily_progress(self.workspace_root, day)
        history[self.current_date] = self.daily_progress
        return history

    def _on_cockpit_progress(self, completed: int, total: int) -> None:
        self._set_header_progress(completed, total)
        self._update_checkin_state()

    def _update_checkin_state(self) -> None:
        if not hasattr(self, "header_status_var"):
            return
        summary = self.plan.workflow or self.plan.tasks
        self._set_header_progress(
            sum(item.completed for item in summary),
            len(summary),
        )
        record_ready = self._record_is_ready()
        requirements_ready = can_check_in(self.plan, self.daily_progress, record_complete=record_ready)
        stats = streak_stats(self._load_progress_history(), self.current_date)
        if self.daily_progress.checked_in:
            self.header_status_var.set(f"今日已打卡 · 当前连胜 {stats['current']} 天")
        elif requirements_ready:
            self.header_status_var.set(f"已完成学习 · 等待打卡 · 当前连胜 {stats['current']} 天")
        elif can_check_in(self.plan, self.daily_progress) and not record_ready:
            self.header_status_var.set(f"今日学习已完成，请填写学习记录 · 连胜 {stats['current']} 天")
        else:
            self.header_status_var.set(f"今日未打卡 · 当前连胜 {stats['current']} 天")
        if self.checkin_button is not None:
            if self.daily_progress.checked_in:
                self.checkin_button.configure(text="今日已打卡", state="disabled")
            elif requirements_ready:
                self.checkin_button.configure(text="完成今日打卡", state="normal")
            elif can_check_in(self.plan, self.daily_progress) and not record_ready:
                self.checkin_button.configure(text="填写记录后打卡", state="normal")
            else:
                self.checkin_button.configure(text="完成全部后打卡", state="normal")

    def _record_is_ready(self) -> bool:
        return record_has_user_content(record_path(self.workspace_root, self.plan))

    def _check_in(self) -> None:
        if self.daily_progress.checked_in:
            return
        if not can_check_in(self.plan, self.daily_progress, record_complete=self._record_is_ready()):
            if not self._record_is_ready() and can_check_in(self.plan, self.daily_progress):
                messagebox.showwarning("还不能打卡", "任务已经完成，请先打开并填写今日学习记录。", parent=self.root)
                return
            pending_steps = sum(1 for task in (self.plan.workflow or self.plan.tasks) if not task.completed)
            pending_carryovers = sum(1 for item in self.daily_progress.carryovers if not item.completed)
            messagebox.showwarning(
                "还不能打卡",
                f"还有 {pending_steps + pending_carryovers} 项内容未完成。\n先完成今日步骤和昨日顺延内容，再点击打卡。",
                parent=self.root,
            )
            return
        mark_checked_in(self.daily_progress)
        save_daily_progress(self.workspace_root, self.daily_progress)
        self._update_checkin_state()
        stats = streak_stats(self._load_progress_history(), self.current_date)
        self.status_var.set(f"打卡成功 · 当前连胜 {stats['current']} 天")
        messagebox.showinfo("打卡成功", f"今天完成了。当前连胜 {stats['current']} 天。", parent=self.root)

    def _rollover_to_date(self, target_day: date) -> bool:
        next_path = daily_plan_path(self.workspace_root, target_day)
        if not next_path.is_file():
            self.status_var.set(f"尚未找到 {target_day.isoformat()} 的学习计划，请先安排明日计划")
            return False
        try:
            next_plan = parse_plan(next_path)
        except (OSError, ValueError) as exc:
            self.status_var.set(f"新日期计划暂时无法读取：{exc}")
            return False
        if next_plan.plan_date != target_day:
            self.status_var.set(f"新计划日期不匹配：{next_plan.plan_date.isoformat()}")
            return False
        if self._focus_timer is not None and self._focus_timer.window.winfo_exists():
            self._focus_timer.close()
        self._focus_timer = None
        if self._reminder_job is not None:
            self.root.after_cancel(self._reminder_job)
            self._reminder_job = None
        previous_plan = None
        previous_path = daily_plan_path(self.workspace_root, target_day - timedelta(days=1))
        if previous_path.is_file():
            try:
                previous_plan = parse_plan(previous_path)
            except (OSError, ValueError):
                previous_plan = None
        self.current_date = target_day
        self.plan = next_plan
        self.plan_path = next_path
        self.daily_progress = prepare_daily_progress(self.workspace_root, target_day, next_plan, previous_plan)
        self.checkin_button = None
        self.carryover_controls = []
        if getattr(self, "outer_frame", None) is not None:
            self.outer_frame.destroy()
        self._build()
        self._start_reminders()
        messagebox.showinfo("已切换到新计划", f"已自动切换到 {target_day.isoformat()} 的学习计划。", parent=self.root)
        return True

    def _start_reminders(self) -> None:
        if not self.reminder_enabled:
            return
        marker = reminder_marker_path(self.workspace_root, self.current_date)
        if should_show_daily_reminder(marker):
            mark_daily_reminder_shown(marker)
            self.root.after(800, self._show_startup_reminder)
        self._reminder_job = self.root.after(60 * 60 * 1000, self._hourly_reminder)

    def _show_startup_reminder(self) -> None:
        if self.root.winfo_exists() and not self.daily_progress.checked_in:
            messagebox.showinfo(
                "今日学习提醒",
                "今天的学习计划还没有完成。打开“今日总览”，按步骤完成并记录成果。",
                parent=self.root,
            )

    def _hourly_reminder(self) -> None:
        if not self.root.winfo_exists():
            return
        observed_day = date.today()
        if should_rollover(self.current_date, observed_day) and self._rollover_to_date(observed_day):
            return
        if not self.daily_progress.checked_in:
            messagebox.showinfo(
                "学习提醒",
                "已经一小时没有完成今日计划了，回来继续下一步吧。",
                parent=self.root,
            )
        self._reminder_job = self.root.after(60 * 60 * 1000, self._hourly_reminder)

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _set_header_progress(self, completed: int, total: int) -> None:
        carryover_completed = sum(item.completed for item in self.daily_progress.carryovers)
        self.header_progress_var.set(combined_progress_text(completed, total, carryover_completed, len(self.daily_progress.carryovers)))

    def _open_resource(self, resource: LearningResource) -> None:
        result = open_resource(self.workspace_root, resource, file_opener=self.file_opener, url_opener=self.url_opener)
        self._set_status(result.message)

    def _build_allowlist(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="临时放行 · 只对今天有效", style="Card.TLabelframe", padding=(12, 6))
        box.grid(row=3, column=0, sticky="ew")
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="应用", style="Section.TLabel").grid(row=0, column=0, padx=(2, 8), pady=6, sticky="w")
        app_entry = ttk.Entry(box)
        app_entry.grid(row=0, column=1, padx=4, pady=6, sticky="ew")
        ttk.Button(box, text="添加应用", style="Secondary.TButton", command=lambda: self._add_app(app_entry)).grid(row=0, column=2, padx=(8, 4), pady=6)
        ttk.Button(box, text="浏览应用 / 快捷方式", style="Secondary.TButton", command=self._browse_app).grid(row=0, column=3, padx=4, pady=6)
        ttk.Label(box, text="网站", style="Section.TLabel").grid(row=1, column=0, padx=(2, 8), pady=6, sticky="w")
        domain_entry = ttk.Entry(box)
        domain_entry.grid(row=1, column=1, padx=4, pady=6, sticky="ew")
        ttk.Button(box, text="添加网站", style="Secondary.TButton", command=lambda: self._add_domain(domain_entry)).grid(row=1, column=2, padx=(8, 4), pady=6)
        ttk.Label(box, text=f"浏览器：{self.browser_status}", style="Muted.TLabel").grid(row=1, column=3, padx=4, pady=6, sticky="w")

    def _on_close(self) -> None:
        if not can_close_panel(enforce=self.enforce_close_guard, locked=True):
            messagebox.showwarning("Study Lock 正在工作", "完成学习并解锁后才能关闭主窗口；紧急情况请使用“紧急恢复”。", parent=self.root)
            return
        if self._reminder_job is not None:
            self.root.after_cancel(self._reminder_job)
            self._reminder_job = None
        if self._health_job is not None:
            self.root.after_cancel(self._health_job)
            self._health_job = None
        if self._focus_timer is not None and self._focus_timer.window.winfo_exists():
            self._focus_timer.close()
        self.root.destroy()

    def _open_record(self) -> None:
        try:
            RecordEditor(self.root, ensure_record(self.workspace_root, self.plan))
        except (OSError, ValueError) as exc:
            messagebox.showwarning("学习记录无法打开", str(exc), parent=self.root)

    def _open_plan_center(self) -> None:
        PlanEditor(self.root, self.workspace_root, self.current_date + timedelta(days=1))

    def _open_notification_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("微信通知设置")
        window.geometry("560x270")
        window.minsize(500, 240)
        window.transient(self.root)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="PushPlus 微信通知", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text="粘贴 PushPlus Token 后保存。Token 只保存在本机。", style="Muted.TLabel").pack(anchor="w", pady=(4, 14))
        token_var = tk.StringVar(value=self.notification_config.token)
        enabled_var = tk.BooleanVar(value=self.notification_config.enabled)
        ttk.Label(frame, text="Token", style="Body.TLabel").pack(anchor="w")
        token_entry = ttk.Entry(frame, textvariable=token_var, show="*")
        token_entry.pack(fill="x", pady=(4, 10))
        ttk.Checkbutton(frame, text="启用微信通知", variable=enabled_var, style="Card.TCheckbutton").pack(anchor="w")
        status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=status_var, style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(14, 0))

        def current_config() -> PushPlusConfig:
            return PushPlusConfig(token_var.get().strip(), enabled_var.get())

        def save() -> None:
            self.notification_config = current_config()
            save_pushplus_config(self.workspace_root, self.notification_config)
            status_var.set("已保存")
            self.status_var.set("微信通知设置已保存")

        def test() -> None:
            config = current_config()
            if not config.enabled or not config.token:
                status_var.set("请先填写 Token 并启用通知")
                return
            test_button.configure(state="disabled")
            status_var.set("正在发送测试消息...")

            def worker() -> None:
                result = send_pushplus(config, "Study Lock 测试消息", "微信通知已经连接成功。")
                self.root.after(0, lambda: finish_test(result.ok, result.message))

            def finish_test(ok: bool, message: str) -> None:
                if test_button.winfo_exists():
                    test_button.configure(state="normal")
                status_var.set(message)
                if ok:
                    self.notification_config = config
                    save_pushplus_config(self.workspace_root, config)

            threading.Thread(target=worker, daemon=True).start()

        ttk.Button(actions, text="保存", style="Primary.TButton", command=save).pack(side="right")
        test_button = ttk.Button(actions, text="发送测试消息", style="Secondary.TButton", command=test)
        test_button.pack(side="right", padx=(0, 8))
        ttk.Button(actions, text="关闭", style="Secondary.TButton", command=window.destroy).pack(side="left")
        token_entry.focus_set()

    def _toggle_override_status(self, message: str) -> None:
        self.status_var.set(message)
        if self.on_overrides_changed:
            self.on_overrides_changed()

    def _add_app(self, entry: ttk.Entry) -> None:
        try:
            add_temporary_app(self.workspace_root / "study-lock/runtime", self.current_date, resolve_application_name(entry.get()))
            entry.delete(0, tk.END)
            self._toggle_override_status("已加入临时应用白名单")
        except ValueError as exc:
            messagebox.showwarning("无法添加应用", str(exc), parent=self.root)

    def _browse_app(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择要放行的应用或快捷方式",
            filetypes=[("可执行程序", "*.exe"), ("Windows 快捷方式", "*.lnk"), ("所有文件", "*.*")],
            parent=self.root,
        )
        if not selected:
            return
        try:
            add_temporary_app(self.workspace_root / "study-lock/runtime", self.current_date, resolve_application_name(selected))
            self._toggle_override_status(f"已加入 {Path(selected).name}")
        except (OSError, ValueError) as exc:
            messagebox.showwarning("无法添加应用", str(exc), parent=self.root)

    def _add_domain(self, entry: ttk.Entry) -> None:
        try:
            add_temporary_domain(self.workspace_root / "study-lock/runtime", self.current_date, entry.get())
            entry.delete(0, tk.END)
            self._toggle_override_status("已加入临时网站白名单")
        except ValueError as exc:
            messagebox.showwarning("无法添加网站", str(exc), parent=self.root)

    def _check_unlock(self) -> UnlockResult:
        result = validate_unlock(self.plan, self.workspace_root, today=self.current_date)
        self.status_var.set(result.reason)
        return result

    def _request_unlock(self) -> None:
        result = self._check_unlock()
        if not result.allowed:
            messagebox.showwarning("暂不能解锁", result.reason, parent=self.root)
            return
        if self.on_unlock:
            outcome = self.on_unlock()
            if getattr(getattr(outcome, "status", None), "value", None) == "UNLOCKED":
                self.root.destroy()

    def _request_recovery(self) -> None:
        if self.recovery_gate is not None:
            return
        self.recovery_gate = RecoveryGate(time.monotonic())
        self.status_var.set("紧急恢复倒计时 60 秒")
        self.root.after(1000, self._recovery_tick)

    def _recovery_tick(self) -> None:
        if self.recovery_gate is None:
            return
        now = time.monotonic()
        remaining = max(0, math.ceil(self.recovery_gate.delay_seconds - (now - self.recovery_gate.started_at)))
        if not self.recovery_gate.ready(now=now):
            self.status_var.set(f"紧急恢复倒计时 {remaining} 秒")
            self.root.after(1000, self._recovery_tick)
            return
        phrase = simpledialog.askstring("紧急恢复", "请输入确认短语：I ACCEPT RECOVERY", parent=self.root)
        if phrase is None:
            self.recovery_gate = None
            self.status_var.set("仍处于 LOCKED")
            return
        if self.on_recovery is None:
            messagebox.showwarning("无法恢复", "当前会话没有配置恢复处理器。", parent=self.root)
            self.recovery_gate = None
            return
        try:
            outcome = self.on_recovery(phrase, self.recovery_gate)
            if getattr(getattr(outcome, "status", None), "value", None) == "RECOVERY":
                self.root.destroy()
            else:
                self.status_var.set("恢复未生效，可以重新请求紧急恢复")
        except (ValueError, OSError, RuntimeError) as exc:
            self.status_var.set("恢复未生效，可以重新请求紧急恢复")
            messagebox.showwarning("无法恢复", str(exc), parent=self.root)
        finally:
            self.recovery_gate = None


class RecoveryPanel:
    def __init__(self, root: tk.Tk, plan: DailyPlan, plan_path: Path, workspace_root: Path, message: str) -> None:
        self.root = root
        self.plan = plan
        self.plan_path = Path(plan_path)
        self.workspace_root = Path(workspace_root)
        self.status_var = tk.StringVar(value="恢复状态：资源已准备")
        configure_ui_style(self.root)
        self.root.title("Study Lock · 今日学习内容")
        self.root.geometry("1240x860")
        self.root.minsize(980, 700)
        outer = ttk.Frame(root, style="App.TFrame", padding=(28, 24))
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(2, weight=1)
        outer.columnconfigure(0, weight=1)

        header = ttk.Frame(outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="今日学习内容", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text=f"{plan.plan_date.isoformat()} · {plan.title} · 恢复模式下仍可继续学习", style="Subtitle.TLabel").pack(anchor="w", pady=(5, 0))

        banner = ttk.LabelFrame(outer, text="恢复状态已记录", style="Notice.TLabelframe", padding=(14, 10))
        banner.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        banner.columnconfigure(1, weight=1)
        tk.Label(banner, text="!", bg=UI_COLORS["amber"], fg="#FFFFFF", width=3, font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, rowspan=2, padx=(0, 12), pady=2, sticky="n")
        ttk.Label(banner, text="今天不会再次触发强制锁定。", style="Notice.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(banner, text="你仍然可以查看今日资料、执行学习任务并记录成果。", style="NoticeBody.TLabel").grid(row=1, column=1, sticky="w", pady=(3, 0))

        tabs = ttk.Notebook(outer, style="App.TNotebook")
        tabs.grid(row=2, column=0, sticky="nsew", pady=(18, 12))
        today_tab = ttk.Frame(tabs, style="App.TFrame", padding=(0, 12, 0, 0))
        project_tab = ttk.Frame(tabs, style="App.TFrame", padding=(0, 12, 0, 0))
        tomorrow_tab = ttk.Frame(tabs, style="App.TFrame", padding=(0, 12, 0, 0))
        tabs.add(today_tab, text="今日总览")
        tabs.add(project_tab, text="项目流程")
        tabs.add(tomorrow_tab, text="明日计划")
        today_scroll = ScrollableFrame(today_tab, height=560)
        today_scroll.pack(fill="both", expand=True)
        cockpit = LearningCockpit(today_scroll.inner, plan, plan_path, workspace_root, url_opener=webbrowser.open, readonly=True, on_status=self.status_var.set)
        cockpit.build()
        build_project_tab(project_tab, plan, on_open_resource=self._open_resource)
        build_tomorrow_tab(tomorrow_tab, workspace_root, plan.plan_date + timedelta(days=1), on_edit=lambda: PlanEditor(root, workspace_root, plan.plan_date + timedelta(days=1)))

        actions = ttk.Frame(outer, style="App.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(actions, textvariable=self.status_var, style="Subtitle.TLabel").pack(side="left", padx=(2, 12))
        ttk.Button(actions, text="打开今天的记录", style="Primary.TButton", command=lambda: self._open_record(workspace_root, plan)).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="安排明日计划", style="Secondary.TButton", command=lambda: PlanEditor(root, workspace_root, plan.plan_date + timedelta(days=1))).pack(side="left")
        ttk.Button(actions, text="关闭", style="Secondary.TButton", command=root.destroy).pack(side="right")

    def _open_resource(self, resource: LearningResource) -> None:
        result = open_resource(self.workspace_root, resource, url_opener=webbrowser.open)
        self.status_var.set(result.message)

    def _open_record(self, workspace_root: Path, plan: DailyPlan) -> None:
        try:
            RecordEditor(self.root, ensure_record(workspace_root, plan))
        except (OSError, ValueError) as exc:
            messagebox.showwarning("学习记录无法打开", str(exc), parent=self.root)


def launch_panel(
    plan: DailyPlan,
    plan_path: Path,
    workspace_root: Path,
    *,
    current_date: date | None = None,
    browser_status: str | None = None,
    on_overrides_changed: Callable[[], object] | None = None,
    on_unlock: Callable[[], object] | None = None,
    on_recovery: Callable[[str, RecoveryGate], object] | None = None,
    url_opener: Callable[[str], object] | None = None,
    file_opener: Callable[[Path], object] | None = None,
    enforce_close_guard: bool = False,
    mode_label: str = "模拟模式",
    reminder_enabled: bool = False,
    health_provider: Callable[[], str | None] | None = None,
) -> None:
    root = tk.Tk()
    StudyPanel(
        root,
        plan,
        plan_path,
        workspace_root,
        current_date=current_date,
        browser_status=browser_status,
        on_overrides_changed=on_overrides_changed,
        on_unlock=on_unlock,
        on_recovery=on_recovery,
        url_opener=url_opener,
        file_opener=file_opener,
        enforce_close_guard=enforce_close_guard,
        mode_label=mode_label,
        reminder_enabled=reminder_enabled,
        health_provider=health_provider,
    )
    root.mainloop()


def launch_recovery_panel(
    plan: DailyPlan,
    plan_path: Path,
    workspace_root: Path,
    *,
    message: str = "当前处于恢复状态。",
) -> None:
    root = tk.Tk()
    RecoveryPanel(root, plan, plan_path, workspace_root, message)
    root.mainloop()
