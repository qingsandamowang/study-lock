from datetime import date
from pathlib import Path

from study_lock.models import DailyPlan, LearningResource, Task
from study_lock.progress import (
    CarryoverTask,
    DailyProgress,
    can_check_in,
    carryover_is_unlocked,
    current_streak,
    load_daily_progress,
    prepare_daily_progress,
    save_daily_progress,
    streak_stats,
)


def make_plan(day: date, *labels: tuple[str, bool]) -> DailyPlan:
    return DailyPlan(
        plan_date=day,
        title="Study",
        tasks=[Task(f"task-{index}", label, completed) for index, (label, completed) in enumerate(labels, 1)],
        allowed_apps=set(),
        allowed_domains=set(),
        learning_record="learning-records/record.md",
    )


def test_prepare_daily_progress_carries_unfinished_tasks_once(tmp_path: Path):
    yesterday = date(2026, 7, 29)
    today = date(2026, 7, 30)
    previous = make_plan(yesterday, ("Read guide", True), ("Run experiment", False))
    current = make_plan(today, ("Review", False))

    progress = prepare_daily_progress(tmp_path, today, current, previous)

    assert [(item.source_date, item.label) for item in progress.carryovers] == [
        (yesterday, "Run experiment")
    ]
    save_daily_progress(tmp_path, progress)
    loaded = load_daily_progress(tmp_path, today)
    prepared_again = prepare_daily_progress(tmp_path, today, current, previous)

    assert loaded == progress
    assert prepared_again.carryovers == progress.carryovers


def test_carryover_keeps_the_previous_step_resource(tmp_path: Path):
    yesterday = date(2026, 7, 29)
    today = date(2026, 7, 30)
    previous = make_plan(yesterday, ("Read guide", False))
    previous.resources = [LearningResource("Readable guide", "PDF", "guide.pdf")]

    progress = prepare_daily_progress(tmp_path, today, make_plan(today, ("Review", False)), previous)

    assert progress.carryovers[0].resource is not None
    assert progress.carryovers[0].resource.title == "Readable guide"
    save_daily_progress(tmp_path, progress)
    loaded = load_daily_progress(tmp_path, today)
    assert loaded.carryovers[0].resource.location == "guide.pdf"


def test_prepare_daily_progress_keeps_older_carryovers_alive(tmp_path: Path):
    yesterday = date(2026, 7, 29)
    today = date(2026, 7, 30)
    previous = make_plan(yesterday, ("Review", True))
    save_daily_progress(
        tmp_path,
        DailyProgress(
            yesterday,
            carryovers=[CarryoverTask(date(2026, 7, 28), "workflow-1", "Older unfinished task")],
        ),
    )

    progress = prepare_daily_progress(tmp_path, today, make_plan(today, ("Today", False)), previous)

    assert [(item.source_date, item.label) for item in progress.carryovers] == [
        (date(2026, 7, 28), "Older unfinished task")
    ]


def test_prepare_daily_progress_orders_carryovers_by_source_date(tmp_path: Path):
    day2 = date(2026, 7, 27)
    day3 = date(2026, 7, 28)
    yesterday = date(2026, 7, 29)
    today = date(2026, 7, 30)
    save_daily_progress(
        tmp_path,
        DailyProgress(
            yesterday,
            carryovers=[CarryoverTask(day2, "workflow-6", "Day2 step")],
        ),
    )
    previous = make_plan(yesterday, ("Day3 step", False))

    progress = prepare_daily_progress(tmp_path, today, make_plan(today, ("Today", True)), previous)

    assert [(item.source_date, item.label) for item in progress.carryovers] == [
        (day2, "Day2 step"),
        (yesterday, "Day3 step"),
    ]


def test_check_in_requires_today_and_carryover_tasks_to_be_complete():
    today = date(2026, 7, 30)
    plan = make_plan(today, ("Review", True))
    progress = DailyProgress(
        day=today,
        carryovers=[CarryoverTask(date(2026, 7, 29), "task-2", "Run experiment")],
    )

    assert can_check_in(plan, progress) is False
    progress.carryovers[0].completed = True
    assert can_check_in(plan, progress) is True
    assert can_check_in(plan, progress, record_complete=False) is False


def test_carryover_is_unlocked_only_for_the_first_incomplete_item():
    items = [
        CarryoverTask(date(2026, 7, 29), "task-1", "First", completed=True),
        CarryoverTask(date(2026, 7, 29), "task-2", "Second"),
        CarryoverTask(date(2026, 7, 29), "task-3", "Third"),
    ]

    assert carryover_is_unlocked(items, 0) is False
    assert carryover_is_unlocked(items, 1) is True
    assert carryover_is_unlocked(items, 2) is False


def test_streak_stats_counts_contiguous_check_ins_and_longest_run():
    progress = {
        date(2026, 7, 25): DailyProgress(date(2026, 7, 25), checked_in=True),
        date(2026, 7, 26): DailyProgress(date(2026, 7, 26), checked_in=True),
        date(2026, 7, 28): DailyProgress(date(2026, 7, 28), checked_in=True),
        date(2026, 7, 29): DailyProgress(date(2026, 7, 29), checked_in=True),
    }

    assert current_streak(progress, date(2026, 7, 30)) == 2
    assert streak_stats(progress, date(2026, 7, 30)) == {
        "current": 2,
        "longest": 2,
        "completed_days": 4,
    }


def test_daily_progress_round_trips_carryover_state(tmp_path: Path):
    progress = DailyProgress(
        day=date(2026, 7, 30),
        checked_in=True,
        completed_at="2026-07-30T20:00:00",
        carryovers=[CarryoverTask(date(2026, 7, 29), "task-1", "Read guide", True)],
    )

    save_daily_progress(tmp_path, progress)

    assert load_daily_progress(tmp_path, progress.day) == progress


def test_corrupt_progress_file_recovers_from_backup(tmp_path: Path):
    day = date(2026, 7, 30)
    progress = DailyProgress(day, checked_in=True, completed_at="2026-07-30T20:00:00")
    save_daily_progress(tmp_path, progress)
    path = tmp_path / "study-lock" / "runtime" / "progress-2026-07-30.json"
    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text("{broken", encoding="utf-8")

    assert load_daily_progress(tmp_path, day) == progress


def test_malformed_progress_shape_recovers_from_valid_backup(tmp_path: Path):
    import json
    from study_lock.progress import progress_path
    day = date(2026, 7, 30)
    expected = DailyProgress(day, checked_in=True)
    save_daily_progress(tmp_path, expected)
    path = progress_path(tmp_path, day)
    path.with_suffix(".json.bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(json.dumps({"day": "2026-07-29", "checked_in": "false", "carryovers": None}), encoding="utf-8")
    assert load_daily_progress(tmp_path, day) == expected


def test_focus_seconds_round_trip_and_accumulate_without_losing_checkin(tmp_path):
    from study_lock.progress import add_focus_seconds
    day = date(2026, 7, 30)
    save_daily_progress(tmp_path, DailyProgress(day, checked_in=True))
    add_focus_seconds(tmp_path, day, 30.5)
    add_focus_seconds(tmp_path, day, 59.5)
    loaded = load_daily_progress(tmp_path, day)
    assert loaded.checked_in is True
    assert loaded.focus_seconds == 90


def test_progress_with_invalid_focus_seconds_recovers_from_backup(tmp_path):
    from study_lock.progress import progress_path
    day = date(2026, 7, 30)
    expected = DailyProgress(day, checked_in=True)
    save_daily_progress(tmp_path, expected)
    path = progress_path(tmp_path, day)
    path.with_suffix(".json.bak").write_bytes(path.read_bytes())
    path.write_text('{"day":"2026-07-30","focus_seconds":-5}', encoding="utf-8")
    assert load_daily_progress(tmp_path, day).checked_in is True
