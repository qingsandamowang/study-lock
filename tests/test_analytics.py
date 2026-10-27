import csv
import json
from datetime import date
from pathlib import Path

import pytest

from study_lock.cli import main


def write_day(workspace, day="2026-07-28", title='Read, "compare" <script>alert(1)</script>', done=True):
    path = workspace / "study-plans" / "daily" / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {day} {title}\n\n## 执行流程\n- [{'x' if done else ' '}] Read（10 分钟）\n- [ ] Compare (20 minutes)\n\n## 任务\n- [ ] Summary\n\n## 允许的应用\n- `code.exe`\n\n## 允许的网站\n- example.com\n\n## 学习记录\n- `notes/{day}.md`\n", encoding="utf-8")
    runtime = workspace / "study-lock" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / f"progress-{day}.json").write_text(json.dumps({"day": day, "checked_in": True, "focus_seconds": 90, "carryovers": []}), encoding="utf-8")
    return path


def test_stats_filters_range_and_exports_totals_csv_and_escaped_html(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    write_day(workspace)
    write_day(workspace, "2026-07-29", title="=HYPERLINK(1)", done=False)
    write_day(workspace, "2026-07-30")
    output = tmp_path / "report"
    before = {str(p): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    assert main(["stats", "--workspace", str(workspace), "--from", "2026-07-28", "--to", "2026-07-29", "--out", str(output)]) == 0
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["totals"]["tasks_total"] == 4
    assert summary["totals"]["tasks_completed"] == 1
    assert summary["totals"]["planned_minutes"] == 60
    assert summary["totals"]["completed_planned_minutes"] == 10
    assert summary["totals"]["focus_minutes"] == 3
    assert summary["totals"]["checked_in_days"] == 2
    with (output / "daily.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["title"] == 'Read, "compare" <script>alert(1)</script>'
    assert rows[1]["title"].startswith("'=HYPERLINK")
    html = (output / "report.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert before == {str(p): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}


def test_stats_keeps_malformed_and_missing_days_visible(tmp_path):
    from study_lock.analytics import collect_stats
    workspace = tmp_path / "workspace"
    path = write_day(workspace)
    path.write_text("broken", encoding="utf-8")
    runtime = workspace / "study-lock" / "runtime"
    (runtime / "progress-2026-07-28.json").write_text('{"carryovers":null,"checked_in":"false"}', encoding="utf-8")
    report = collect_stats(workspace, date(2026, 7, 28), date(2026, 7, 29))
    assert len(report["days"]) == 2
    assert report["totals"]["tasks_total"] == 0
    assert report["totals"]["checked_in_days"] == 0
    assert len(report["warnings"]) >= 3


def test_stats_rejects_reversed_range_without_creating_output(tmp_path, capsys):
    output = tmp_path / "report"
    assert main(["stats", "--workspace", str(tmp_path), "--from", "2026-07-29", "--to", "2026-07-28", "--out", str(output)]) == 1
    assert not output.exists()


def test_stats_uses_valid_backup_and_reports_the_recovery(tmp_path):
    from study_lock.analytics import collect_stats
    workspace = tmp_path / "workspace"
    write_day(workspace)
    path = workspace / "study-lock" / "runtime" / "progress-2026-07-28.json"
    path.with_suffix(".json.bak").write_bytes(path.read_bytes())
    path.write_text('{"focus_seconds":' + "9" * 400 + '}', encoding="utf-8")
    report = collect_stats(workspace, date(2026, 7, 28), date(2026, 7, 28))
    assert report["totals"]["focus_minutes"] == 1.5
    assert report["totals"]["checked_in_days"] == 1
    assert any("recovered from backup" in warning for warning in report["warnings"])
