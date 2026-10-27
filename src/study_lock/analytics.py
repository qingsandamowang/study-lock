"""Local learning statistics, with explicit estimates and visible data issues."""
from __future__ import annotations

import csv
import html
from datetime import date, timedelta
from pathlib import Path

from .plan_parser import parse_plan
from .progress import load_daily_progress
from .records import record_has_user_content
from .storage import resolve_workspace_path, atomic_write_json
from .timer import parse_stage_duration


def _progress(workspace: Path, day: date, warnings: list[str]):
    progress = load_daily_progress(workspace, day, warnings=warnings)
    return progress, progress.focus_seconds


def collect_stats(workspace: Path, start: date, end: date) -> dict:
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError("Workspace must be an existing directory")
    if start > end:
        raise ValueError("--from must be on or before --to")
    if (end - start).days > 36600:
        raise ValueError("Date range must be at most 100 years")
    warnings: list[str] = []
    rows = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        issues_before = len(warnings)
        row = {"date": day.isoformat(), "title": "", "plan_found": False, "tasks_total": 0, "tasks_completed": 0, "completion_percent": 0.0, "plan_complete": False, "planned_minutes": 0, "completed_planned_minutes": 0, "focus_minutes": 0.0, "checked_in": False, "record_has_notes": False, "carryovers_total": 0, "carryovers_completed": 0}
        plan_path = workspace / "study-plans" / "daily" / f"{day.isoformat()}.md"
        try:
            plan = parse_plan(plan_path)
            if plan.plan_date != day:
                raise ValueError("plan heading date differs from filename date")
            tasks = plan.workflow or plan.tasks
            row.update(title=plan.title, plan_found=True, tasks_total=len(tasks), tasks_completed=sum(task.completed for task in tasks), plan_complete=plan.is_complete())
            row["completion_percent"] = round(row["tasks_completed"] / len(tasks) * 100, 2)
            # Only explicit durations are estimates; never invent time for tasks without durations.
            row["planned_minutes"] = sum(parse_stage_duration(task.label, default_seconds=0) // 60 for task in tasks)
            row["completed_planned_minutes"] = sum(parse_stage_duration(task.label, default_seconds=0) // 60 for task in tasks if task.completed)
            record = resolve_workspace_path(workspace, plan.learning_record)
            row["record_has_notes"] = record_has_user_content(record)
        except (OSError, ValueError) as exc:
            warnings.append(f"{day}: plan unavailable or invalid: {exc.__class__.__name__}: {str(exc).replace(str(workspace), '<workspace>')}")
        progress, seconds = _progress(workspace, day, warnings)
        if progress is not None:
            row["checked_in"] = progress.checked_in
            row["carryovers_total"] = len(progress.carryovers)
            row["carryovers_completed"] = sum(item.completed for item in progress.carryovers)
        row["focus_minutes"] = seconds / 60
        row["issue_count"] = len(warnings) - issues_before
        rows.append(row)
    totals = {key: sum(row[key] for row in rows) for key in ("tasks_total", "tasks_completed", "planned_minutes", "completed_planned_minutes", "focus_minutes", "carryovers_total", "carryovers_completed")}
    totals.update(days_in_range=len(rows), days_with_plan=sum(row["plan_found"] for row in rows), completed_plan_days=sum(row["plan_complete"] for row in rows), checked_in_days=sum(row["checked_in"] for row in rows))
    totals["completion_percent"] = round(totals["tasks_completed"] / totals["tasks_total"] * 100, 2) if totals["tasks_total"] else 0.0
    totals["focus_minutes"] = round(totals["focus_minutes"], 2)
    for row in rows:
        row["focus_minutes"] = round(row["focus_minutes"], 2)
    return {"schema_version": 1, "from": start.isoformat(), "to": end.isoformat(), "minute_semantics": "planned_minutes and completed_planned_minutes use explicit task durations; focus_minutes uses recorded timer seconds (legacy records default to zero)", "totals": totals, "days": rows, "warnings": warnings}


def _csv_safe(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_stats(report: dict, output: Path) -> list[Path]:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    json_path, csv_path, html_path = (output / name for name in ("summary.json", "daily.csv", "report.html"))
    atomic_write_json(json_path, report)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report["days"][0]))
        writer.writeheader()
        writer.writerows({key: _csv_safe(value) for key, value in row.items()} for row in report["days"])
    escape = lambda value: html.escape(str(value), quote=True)
    totals = report["totals"]
    body = "".join(f"<tr><td>{escape(row['date'])}</td><td>{escape(row['title'])}</td><td>{row['tasks_completed']} / {row['tasks_total']}</td><td>{row['planned_minutes']}</td><td>{row['completed_planned_minutes']}</td><td>{row['focus_minutes']}</td><td>{'Yes' if row['checked_in'] else 'No'}</td></tr>" for row in report["days"])
    warning_html = "".join(f"<li>{escape(item)}</li>" for item in report["warnings"])
    html_path.write_text(f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Study Lock learning report</title>
<style>body{{font:16px system-ui,sans-serif;color:#183153;background:#f4f7fb;margin:0;padding:32px}}main{{max-width:1100px;margin:auto}}h1{{font-size:32px}}.summary,table{{background:white;border-radius:12px;padding:20px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #dce4ef}}.scroll{{overflow:auto}}p{{line-height:1.6}}small{{color:#51677f}}</style>
<main><h1>Study Lock · Learning report</h1><p>{escape(report['from'])} — {escape(report['to'])}</p>
<div class="summary">Completed tasks: <strong>{totals['tasks_completed']} / {totals['tasks_total']}</strong> · Completion: <strong>{totals['completion_percent']}%</strong> · Check-ins: <strong>{totals['checked_in_days']}</strong> · Recorded focus: <strong>{totals['focus_minutes']} min</strong></div>
<p><small>{escape(report['minute_semantics'])}. Task completion and check-in are separate signals. No note contents are exported.</small></p>
<div class="scroll"><table><thead><tr><th>Date</th><th>Plan</th><th>Tasks</th><th>Planned min</th><th>Completed estimate min</th><th>Recorded focus min</th><th>Check-in</th></tr></thead><tbody>{body}</tbody></table></div>
<h2>Data issues ({len(report['warnings'])})</h2><ul>{warning_html or '<li>None</li>'}</ul><p><small>Generated locally. This report contains no scripts or external resources.</small></p></main></html>''', encoding="utf-8")
    return [json_path, csv_path, html_path]
