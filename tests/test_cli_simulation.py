from datetime import date
from pathlib import Path

from study_lock.cli import main, simulate_plan
from study_lock.state import LockState


def test_simulation_does_not_enforce_and_reports_safe_config_for_template(tmp_path: Path):
    template = tmp_path / "template.md"
    template.write_text("# YYYY-MM-DD 学习计划\n", encoding="utf-8")

    report = simulate_plan(template, tmp_path, today=date(2026, 7, 28))

    assert report.state is LockState.SAFE_CONFIG
    assert report.enforced is False
    assert "safe" in report.message.lower()


def test_cli_simulate_prints_state(capsys, tmp_path: Path):
    plan = tmp_path / "2026-07-28.md"
    plan.write_text(
        "# 2026-07-28 学习计划\n\n"
        "## 任务\n- [ ] Read card\n\n"
        "## 允许的应用\n- `Code.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        "## 学习记录\n- `record.md`\n",
        encoding="utf-8",
    )

    assert main(["simulate", "--plan", str(plan), "--workspace", str(tmp_path), "--date", "2026-07-28"]) == 0
    output = capsys.readouterr().out
    assert "LOCKED" in output
    assert "simulation" in output.lower()
