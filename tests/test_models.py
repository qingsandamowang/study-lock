from datetime import date

from study_lock.models import DailyPlan, Task


def test_plan_is_complete_only_when_all_required_tasks_are_checked():
    plan = DailyPlan(
        plan_date=date(2026, 7, 28),
        title="Vision Day 1",
        tasks=[Task("a", "Read abstract", True), Task("b", "Write card", False)],
        allowed_apps={"code.exe"},
        allowed_domains={"chatgpt.com"},
        learning_record="learning-records/2026-07-28.md",
    )

    assert plan.is_complete() is False
    plan.tasks[1].completed = True
    assert plan.is_complete() is True
