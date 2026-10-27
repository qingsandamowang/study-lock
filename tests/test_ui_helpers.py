from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from study_lock.cli import main
from study_lock.models import LearningResource
from study_lock.ui import (
    add_temporary_app,
    add_temporary_domain,
    can_close_panel,
    group_resources,
    load_overrides,
    progress_percent,
    progress_text,
    combined_progress_text,
    reminder_marker_path,
    mark_daily_reminder_shown,
    resolve_application_name,
    should_show_daily_reminder,
    UI_COLORS,
    wheel_scroll_units,
    calendar_day_state,
    daily_plan_path,
    should_rollover,
)


def test_temporary_allowlists_are_scoped_to_one_date(tmp_path: Path):
    today = date(2026, 7, 28)
    tomorrow = date(2026, 7, 29)

    add_temporary_app(tmp_path, today, "Code.exe")
    add_temporary_domain(tmp_path, today, "chatgpt.com")

    assert load_overrides(tmp_path, today).apps == {"code.exe"}
    assert load_overrides(tmp_path, today).domains == {"chatgpt.com"}
    assert load_overrides(tmp_path, tomorrow).apps == set()
    assert load_overrides(tmp_path, tomorrow).domains == set()


def test_cli_ui_dispatches_to_panel_in_simulation_mode(monkeypatch, tmp_path: Path):
    plan = tmp_path / "2026-07-28.md"
    plan.write_text(
        "# 2026-07-28 学习计划\n\n"
        "## 任务\n- [ ] Read card\n\n"
        "## 允许的应用\n- `Code.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        "## 学习记录\n- `record.md`\n",
        encoding="utf-8",
    )
    called = []
    monkeypatch.setattr(
        "study_lock.cli.launch_panel",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    result = main(
        [
            "ui",
            "--mode",
            "simulate",
            "--plan",
            str(plan),
            "--workspace",
            str(tmp_path),
            "--date",
            "2026-07-28",
        ]
    )

    assert result == 0
    assert called and called[0][0][1] == plan
    assert "on_unlock" in called[0][1]


def test_cli_reminder_mode_does_not_start_a_lock_session(monkeypatch, tmp_path: Path):
    plan = tmp_path / "2026-07-28.md"
    plan.write_text(
        "# 2026-07-28 学习计划\n\n"
        "## 任务\n- [ ] Read card\n\n"
        "## 允许的应用\n- `Code.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        "## 学习记录\n- `record.md`\n",
        encoding="utf-8",
    )
    called = []

    monkeypatch.setattr("study_lock.cli.launch_panel", lambda *args, **kwargs: called.append((args, kwargs)))

    class UnexpectedSession:
        def __init__(self, *args, **kwargs):
            raise AssertionError("reminder mode must not create StudyLockSession")

    monkeypatch.setattr("study_lock.cli.StudyLockSession", UnexpectedSession)

    result = main(
        [
            "ui",
            "--mode",
            "reminder",
            "--plan",
            str(plan),
            "--workspace",
            str(tmp_path),
            "--date",
            "2026-07-28",
        ]
    )

    assert result == 0
    assert called and called[0][1]["reminder_enabled"] is True
    assert called[0][1]["enforce_close_guard"] is False


def test_resolve_application_name_accepts_exe_and_shortcut_target():
    assert resolve_application_name("C:/Tools/Code.exe") == "code.exe"

    result = resolve_application_name(
        "C:/Users/Public/Desktop/Editor.lnk",
        shortcut_resolver=lambda path: Path("D:/Apps/Editor/Editor.exe"),
    )

    assert result == "editor.exe"


def test_locked_enforce_panel_cannot_be_closed_but_other_modes_can():
    assert can_close_panel(enforce=True, locked=True) is False
    assert can_close_panel(enforce=True, locked=False) is True
    assert can_close_panel(enforce=False, locked=True) is True


def test_group_resources_keeps_resource_order_by_display_kind():
    resources = [
        LearningResource("论文 A", "PDF", "a.pdf"),
        LearningResource("视频", "视频", "https://example.com/video"),
        LearningResource("论文 B", "PDF", "b.pdf"),
    ]

    grouped = group_resources(resources)

    assert list(grouped) == ["PDF", "视频"]
    assert [item.title for item in grouped["PDF"]] == ["论文 A", "论文 B"]


def test_ui_theme_uses_the_learning_cockpit_palette_and_safe_progress():
    assert UI_COLORS["background"] == "#F4F7FB"
    assert UI_COLORS["primary"] == "#2F80ED"
    assert progress_percent(0, 0) == 0
    assert progress_percent(2, 6) == 33
    assert progress_percent(6, 6) == 100


def test_progress_text_is_stable_for_the_header():
    assert progress_text(2, 6) == "进度 2 / 6 · 33%"


def test_combined_progress_includes_today_and_carryover_tasks():
    assert combined_progress_text(0, 5, 0, 6) == "总进度 0 / 11 · 今日 0 / 5 · 补做 0 / 6"


def test_wheel_scroll_units_supports_windows_and_x11_deltas():
    assert wheel_scroll_units(120) == -1
    assert wheel_scroll_units(-120) == 1
    assert wheel_scroll_units(0) == 0


def test_calendar_does_not_mark_dates_before_study_lock_as_missed():
    today = date(2026, 7, 30)
    assert calendar_day_state(date(2026, 7, 20), today, None) == "unknown"
    assert calendar_day_state(date(2026, 7, 29), today, type("Progress", (), {"checked_in": False})()) == "missed"
    assert calendar_day_state(today, today, None) == "today"


def test_rollover_only_happens_when_system_date_moves_forward():
    current = date(2026, 7, 30)
    assert should_rollover(current, date(2026, 7, 31)) is True
    assert should_rollover(current, current) is False
    assert should_rollover(current, date(2026, 7, 29)) is False
    assert daily_plan_path(Path("C:/workspace"), date(2026, 7, 31)).name == "2026-07-31.md"


def test_daily_reminder_marker_is_written_once_per_date(tmp_path: Path):
    marker = reminder_marker_path(tmp_path, date(2026, 7, 29))

    assert should_show_daily_reminder(marker) is True
    mark_daily_reminder_shown(marker)
    assert marker.is_file()
    assert should_show_daily_reminder(marker) is False


def test_cli_opens_recovery_dashboard_after_recovery_marker(monkeypatch, tmp_path: Path):
    plan = tmp_path / "2026-07-28.md"
    plan.write_text(
        "# 2026-07-28 学习计划\n\n"
        "## 任务\n- [ ] Read card\n\n"
        "## 允许的应用\n- `Code.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        "## 学习记录\n- `record.md`\n",
        encoding="utf-8",
    )
    marker = tmp_path / "study-lock/runtime/recovery-2026-07-28.marker"
    marker.parent.mkdir(parents=True)
    marker.write_text("recovery approved\n", encoding="utf-8")
    called = []
    monkeypatch.setattr(
        "study_lock.cli.launch_recovery_panel",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    result = main(
        [
            "ui",
            "--mode",
            "enforce",
            "--plan",
            str(plan),
            "--workspace",
            str(tmp_path),
            "--date",
            "2026-07-28",
        ]
    )

    assert result == 0
    assert called and called[0][0][1] == plan


def test_learning_steps_keep_resource_buttons_visible(monkeypatch):
    plan_path = (Path(__file__).resolve().parents[1] / "examples/demo-workspace") / "study-plans/daily/2026-07-29.md"
    workspace = plan_path.parents[1]
    from study_lock.plan_parser import parse_plan
    from study_lock.ui import StudyPanel

    plan = parse_plan(plan_path)
    try:
        root = tk.Tk()
    except tk.TclError:
        return
    root.withdraw()
    panel = StudyPanel(root, plan, plan_path, workspace, current_date=date(2026, 7, 29), reminder_enabled=True)
    root.update_idletasks()

    for row, *_ in panel.cockpit.step_views[:3]:
        buttons = [child for child in row.winfo_children() if isinstance(child, ttk.Button)]
        assert buttons
        assert buttons[0].winfo_width() >= 80
        assert str(buttons[0].cget("style")) == "Primary.TButton"

    panel._on_close()


def test_reminder_panel_exposes_focus_calendar_and_checkin_controls(tmp_path: Path):
    plan_path = tmp_path / "study-plans" / "daily" / "2026-07-30.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        "# 2026-07-30 学习计划\n\n"
        "## 执行流程\n- [ ] 步骤 1（10 分钟）：阅读\n\n"
        "## 允许的应用\n- `chrome.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        "## 学习记录\n- `learning-records/2026-07-30.md`\n\n"
        "## 任务\n- [ ] 完成学习\n",
        encoding="utf-8",
    )
    from study_lock.plan_parser import parse_plan
    from study_lock.ui import StudyPanel

    plan = parse_plan(plan_path)
    try:
        root = tk.Tk()
    except tk.TclError:
        return
    root.withdraw()
    panel = StudyPanel(root, plan, plan_path, tmp_path, current_date=date(2026, 7, 30), reminder_enabled=True)
    root.update_idletasks()
    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)

    nested_text = " ".join(str(widget.cget("text")) for widget in walk(panel.root) if isinstance(widget, ttk.Button))
    assert "专注计时器" in nested_text
    assert "打卡与日历" in nested_text
    assert "完成全部后打卡" in nested_text
    panel._on_close()


def test_carryover_rows_expose_their_previous_resource_button(tmp_path: Path):
    daily = tmp_path / "study-plans" / "daily"
    daily.mkdir(parents=True)
    (daily / "2026-07-29.md").write_text(
        "# 2026-07-29 学习计划\n\n"
        "## 执行流程\n- [ ] 步骤 1（10 分钟）：阅读导读\n\n"
        "## 论文与资料\n- 快速导读\n  - 类型：PDF\n  - 路径：guide.pdf\n\n"
        "## 允许的应用\n- `chrome.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        "## 学习记录\n- `learning-records/2026-07-29.md`\n\n"
        "## 任务\n- [ ] 完成学习\n",
        encoding="utf-8",
    )
    current_path = daily / "2026-07-30.md"
    current_path.write_text(
        "# 2026-07-30 学习计划\n\n"
        "## 执行流程\n- [ ] 步骤 1（10 分钟）：今日学习\n\n"
        "## 允许的应用\n- `chrome.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        "## 学习记录\n- `learning-records/2026-07-30.md`\n\n"
        "## 任务\n- [ ] 完成学习\n",
        encoding="utf-8",
    )
    from study_lock.plan_parser import parse_plan
    from study_lock.ui import StudyPanel

    try:
        root = tk.Tk()
    except tk.TclError:
        return
    root.withdraw()
    panel = StudyPanel(root, parse_plan(current_path), current_path, tmp_path, current_date=date(2026, 7, 30), reminder_enabled=True)
    root.update_idletasks()

    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)

    button_text = " ".join(str(widget.cget("text")) for widget in walk(panel.root) if isinstance(widget, ttk.Button))
    assert "打开资料" in button_text
    assert "补做 0 / 1" in panel.header_progress_var.get()
    panel._on_close()


def test_carryover_checkboxes_unlock_in_order(tmp_path: Path):
    daily = tmp_path / "study-plans" / "daily"
    daily.mkdir(parents=True)
    (daily / "2026-07-29.md").write_text(
        "# 2026-07-29 学习计划\n\n"
        "## 执行流程\n- [ ] 步骤 1（10 分钟）：第一步\n- [ ] 步骤 2（10 分钟）：第二步\n\n"
        "## 允许的应用\n- `chrome.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        "## 学习记录\n- `learning-records/2026-07-29.md`\n\n"
        "## 任务\n- [ ] 完成学习\n",
        encoding="utf-8",
    )
    current_path = daily / "2026-07-30.md"
    current_path.write_text(
        "# 2026-07-30 学习计划\n\n"
        "## 执行流程\n- [ ] 今日步骤（10 分钟）\n\n"
        "## 允许的应用\n- `chrome.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        "## 学习记录\n- `learning-records/2026-07-30.md`\n\n"
        "## 任务\n- [ ] 完成学习\n",
        encoding="utf-8",
    )
    from study_lock.plan_parser import parse_plan
    from study_lock.ui import StudyPanel

    try:
        root = tk.Tk()
    except tk.TclError:
        return
    root.withdraw()
    panel = StudyPanel(root, parse_plan(current_path), current_path, tmp_path, current_date=date(2026, 7, 30), reminder_enabled=True)
    root.update_idletasks()
    assert [control[2].cget("state") for control in panel.carryover_controls] == ["normal", "disabled"]

    panel.carryover_controls[0][2].invoke()

    assert [control[2].cget("state") for control in panel.carryover_controls] == ["disabled", "normal"]
    panel._on_close()
