from datetime import date
from pathlib import Path

from study_lock.models import DailyPlan, Task
from study_lock.unlock import validate_unlock


def make_plan(record: str = "learning-records/today.md") -> DailyPlan:
    return DailyPlan(
        plan_date=date(2026, 7, 28),
        title="Vision Day 1",
        tasks=[Task("task-1", "Write card", True)],
        allowed_apps=set(),
        allowed_domains=set(),
        learning_record=record,
    )


def test_unlock_requires_a_completed_task_list(tmp_path: Path):
    plan = make_plan()
    plan.tasks[0].completed = False
    (tmp_path / "learning-records").mkdir()
    (tmp_path / "learning-records/today.md").write_text("record", encoding="utf-8")

    result = validate_unlock(plan, tmp_path, today=date(2026, 7, 28))

    assert result.allowed is False
    assert result.code == "tasks_incomplete"


def test_unlock_rejects_missing_or_empty_learning_record(tmp_path: Path):
    missing = validate_unlock(make_plan(), tmp_path, today=date(2026, 7, 28))
    assert missing.allowed is False
    assert missing.code == "record_missing"

    record = tmp_path / "learning-records/today.md"
    record.parent.mkdir()
    record.write_text(" \n", encoding="utf-8")
    empty = validate_unlock(make_plan(), tmp_path, today=date(2026, 7, 28))
    assert empty.allowed is False
    assert empty.code == "record_empty"


def test_unlock_accepts_completed_tasks_and_non_empty_record(tmp_path: Path):
    record = tmp_path / "learning-records/today.md"
    record.parent.mkdir()
    record.write_text("今天完成了论文卡片。", encoding="utf-8")

    result = validate_unlock(make_plan(), tmp_path, today=date(2026, 7, 28))

    assert result.allowed is True
    assert result.code == "ok"


def test_unlock_rejects_untouched_generated_template(tmp_path: Path):
    from study_lock.records import ensure_record
    plan = make_plan()
    ensure_record(tmp_path, plan)
    result = validate_unlock(plan, tmp_path, today=date(2026, 7, 28))
    assert not result.allowed
    assert result.code == "record_no_notes"


def test_unlock_checks_detailed_workflow_when_present(tmp_path: Path):
    record = tmp_path / "learning-records/today.md"
    record.parent.mkdir()
    record.write_text("record", encoding="utf-8")
    plan = make_plan()
    plan.workflow = [Task("workflow-1", "Read paper", False)]

    result = validate_unlock(plan, tmp_path, today=date(2026, 7, 28))

    assert result.allowed is False
    assert result.code == "tasks_incomplete"


def test_unlock_rejects_wrong_date_and_path_escape(tmp_path: Path):
    record = tmp_path / "learning-records/today.md"
    record.parent.mkdir()
    record.write_text("record", encoding="utf-8")

    wrong_date = validate_unlock(make_plan(), tmp_path, today=date(2026, 7, 29))
    assert wrong_date.allowed is False
    assert wrong_date.code == "plan_date_mismatch"

    escape = validate_unlock(
        make_plan("../outside.md"), tmp_path, today=date(2026, 7, 28)
    )
    assert escape.allowed is False
    assert escape.code == "record_path_invalid"
