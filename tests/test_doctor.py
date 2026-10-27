import json
from datetime import date
from pathlib import Path

import pytest

from study_lock.cli import main


def plan_in(workspace, *, record="notes/today.md", resource="resources/guide.md", domain="example.com"):
    workspace.mkdir(exist_ok=True)
    path = workspace / "2026-07-28.md"
    path.write_text(f"# 2026-07-28 Demo\n\n## 任务\n- [ ] Read\n\n## 允许的应用\n- `code.exe`\n\n## 允许的网站\n- {domain}\n\n## 学习记录\n- `{record}`\n\n## 论文与资料\n- Guide\n  - 路径：{resource}\n", encoding="utf-8")
    resources = workspace / "resources"
    resources.mkdir(exist_ok=True)
    (resources / "guide.md").write_text("generic guide", encoding="utf-8")
    return path


def test_doctor_valid_config_is_read_only_and_browser_optional(tmp_path, capsys, monkeypatch):
    plan = plan_in(tmp_path)
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr("study_lock.cli.StudyLockSession", lambda *_args, **_kwargs: pytest.fail("doctor must not create a session"))
    monkeypatch.setattr("psutil.process_iter", lambda *_args, **_kwargs: pytest.fail("doctor must not inspect processes"))
    monkeypatch.setattr("study_lock.doctor.find_chrome_executable", lambda: pytest.fail("browser check must remain optional"))
    assert main(["doctor", "--workspace", str(tmp_path), "--plan", str(plan), "--date", "2026-07-28", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert not (tmp_path / "study-lock").exists()


@pytest.mark.parametrize("change", ["date", "plan", "record_escape", "resource_escape", "missing_resource", "rules", "browser"])
def test_doctor_reports_invalid_configuration(tmp_path, capsys, change):
    plan = plan_in(tmp_path, record="../outside.md" if change == "record_escape" else "notes/today.md", resource="../outside.md" if change == "resource_escape" else "missing.md" if change == "missing_resource" else "resources/guide.md", domain="example.com:443" if change == "rules" else "example.com")
    if change == "plan":
        plan.write_text("broken", encoding="utf-8")
    args = ["doctor", "--workspace", str(tmp_path), "--plan", str(plan), "--date", "2026-07-29" if change == "date" else "2026-07-28", "--json"]
    if change == "browser":
        args.extend(["--browser", str(tmp_path / "missing-chrome.exe")])
    assert main(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["ok"]
    assert any(item["level"] == "error" for item in report["checks"])


def test_doctor_rejects_plan_outside_workspace(tmp_path, capsys):
    plan = plan_in(tmp_path)
    workspace = tmp_path / "nested"
    workspace.mkdir()
    assert main(["doctor", "--workspace", str(workspace), "--plan", str(plan), "--date", "2026-07-28", "--json"]) == 1
    assert "plan_path" in capsys.readouterr().out


@pytest.mark.parametrize("mode,expected,level", [("reminder", 0, "warning"), ("enforce", 1, "error")])
def test_doctor_reports_resource_ports_that_the_proxy_cannot_open(tmp_path, capsys, mode, expected, level):
    plan = plan_in(tmp_path, resource="https://example.com:8443/paper")
    assert main(["doctor", "--workspace", str(tmp_path), "--plan", str(plan), "--date", "2026-07-28", "--mode", mode, "--json"]) == expected
    report = json.loads(capsys.readouterr().out)
    assert any(item["code"] == "resource_1" and item["level"] == level and "port" in item["message"] for item in report["checks"])
