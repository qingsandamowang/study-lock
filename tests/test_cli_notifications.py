from datetime import date
from pathlib import Path

from study_lock.cli import notify_previous_incomplete_plan
from study_lock.notifications import PushPlusConfig
from study_lock.progress import DailyProgress, save_daily_progress


def write_plan(path: Path, checked: str) -> None:
    path.write_text(
        f"# 2026-07-29 学习计划\n\n"
        f"## 执行流程\n- [{checked}] 步骤 1\n\n"
        f"## 任务\n- [{checked}] 完成学习\n\n"
        "## 允许的应用\n- `chrome.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        "## 学习记录\n- `learning-records/2026-07-29.md`\n",
        encoding="utf-8",
    )


def configure_pushplus(monkeypatch, sent: list):
    monkeypatch.setattr(
        "study_lock.cli.load_pushplus_config",
        lambda _workspace: PushPlusConfig(token="token", enabled=True),
    )
    monkeypatch.setattr(
        "study_lock.cli.send_pushplus",
        lambda config, title, content: sent.append((config, title, content)) or type("Result", (), {"ok": True, "message": "ok"})(),
    )


def test_previous_incomplete_plan_is_sent_once_and_marked(monkeypatch, tmp_path: Path):
    daily = tmp_path / "study-plans" / "daily"
    daily.mkdir(parents=True)
    write_plan(daily / "2026-07-29.md", " ")
    sent = []
    configure_pushplus(monkeypatch, sent)

    assert notify_previous_incomplete_plan(tmp_path, date(2026, 7, 30)) is True
    assert notify_previous_incomplete_plan(tmp_path, date(2026, 7, 30)) is False
    assert len(sent) == 1
    assert "2026-07-29" in sent[0][2]


def test_completed_plan_without_check_in_sends_streak_break_warning(monkeypatch, tmp_path: Path):
    daily = tmp_path / "study-plans" / "daily"
    daily.mkdir(parents=True)
    write_plan(daily / "2026-07-29.md", "x")
    save_daily_progress(tmp_path, DailyProgress(date(2026, 7, 29), checked_in=False))
    sent = []
    configure_pushplus(monkeypatch, sent)

    assert notify_previous_incomplete_plan(tmp_path, date(2026, 7, 30)) is True
    assert "打卡" in sent[0][2]
