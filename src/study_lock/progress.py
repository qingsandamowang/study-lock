from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import DailyPlan, LearningResource


@dataclass
class CarryoverTask:
    source_date: date
    task_id: str
    label: str
    completed: bool = False
    resource: LearningResource | None = None


@dataclass
class DailyProgress:
    day: date
    checked_in: bool = False
    completed_at: str | None = None
    carryovers: list[CarryoverTask] = field(default_factory=list)


def progress_path(workspace_root: Path, day: date) -> Path:
    return Path(workspace_root) / "study-lock" / "runtime" / f"progress-{day.isoformat()}.json"


def _carryover_to_dict(item: CarryoverTask) -> dict[str, object]:
    payload = asdict(item)
    payload["source_date"] = item.source_date.isoformat()
    return payload


def _carryover_from_dict(payload: object) -> CarryoverTask | None:
    if not isinstance(payload, dict):
        return None
    try:
        resource_payload = payload.get("resource")
        resource = LearningResource(**resource_payload) if isinstance(resource_payload, dict) else None
        return CarryoverTask(
            source_date=date.fromisoformat(str(payload["source_date"])),
            task_id=str(payload["task_id"]),
            label=str(payload["label"]),
            completed=bool(payload.get("completed", False)),
            resource=resource,
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_daily_progress(workspace_root: Path, day: date) -> DailyProgress:
    path = progress_path(workspace_root, day)
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        carryovers = [
            item
            for raw in payload.get("carryovers", [])
            if (item := _carryover_from_dict(raw)) is not None
        ]
        return DailyProgress(
            day=day,
            checked_in=bool(payload.get("checked_in", False)),
            completed_at=str(payload["completed_at"]) if payload.get("completed_at") else None,
            carryovers=carryovers,
        )
    return DailyProgress(day)


def save_daily_progress(workspace_root: Path, progress: DailyProgress) -> Path:
    path = progress_path(workspace_root, progress.day)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "day": progress.day.isoformat(),
        "checked_in": progress.checked_in,
        "completed_at": progress.completed_at,
        "carryovers": [_carryover_to_dict(item) for item in progress.carryovers],
    }
    if path.is_file():
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        else:
            shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", prefix=f".{path.stem}-", dir=path.parent, delete=False) as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return path


def unfinished_tasks(plan: DailyPlan) -> list[CarryoverTask]:
    tasks = plan.workflow or plan.tasks
    carryovers: list[CarryoverTask] = []
    for index, task in enumerate(tasks):
        if task.completed:
            continue
        resource = plan.resources[index] if index < len(plan.resources) else None
        carryovers.append(CarryoverTask(plan.plan_date, task.task_id, task.label, resource=resource))
    return carryovers


def prepare_daily_progress(
    workspace_root: Path,
    day: date,
    current_plan: DailyPlan,
    previous_plan: DailyPlan | None = None,
) -> DailyProgress:
    progress = load_daily_progress(workspace_root, day)
    if not progress.carryovers and previous_plan is not None:
        pending = unfinished_tasks(previous_plan)
        previous_progress = load_daily_progress(workspace_root, day - timedelta(days=1))
        pending.extend(item for item in previous_progress.carryovers if not item.completed)
        if pending:
            pending.sort(key=lambda item: item.source_date)
            progress.carryovers = pending
            save_daily_progress(workspace_root, progress)
    elif progress.carryovers and previous_plan is not None:
        changed = False
        tasks = previous_plan.workflow or previous_plan.tasks
        for item in progress.carryovers:
            if item.resource is not None or item.source_date != previous_plan.plan_date:
                continue
            try:
                item_number = int(item.task_id.rsplit("-", 1)[1]) - 1
            except (IndexError, ValueError):
                continue
            if 0 <= item_number < len(previous_plan.resources) and item_number < len(tasks):
                item.resource = previous_plan.resources[item_number]
                changed = True
        if changed:
            save_daily_progress(workspace_root, progress)
    return progress


def carryover_is_unlocked(carryovers: list[CarryoverTask], index: int) -> bool:
    if index < 0 or index >= len(carryovers):
        return False
    first_incomplete = next((position for position, item in enumerate(carryovers) if not item.completed), None)
    return first_incomplete == index


def can_check_in(plan: DailyPlan, progress: DailyProgress, *, record_complete: bool = True) -> bool:
    return plan.is_complete() and all(item.completed for item in progress.carryovers) and record_complete


def mark_checked_in(progress: DailyProgress, *, now: datetime | None = None) -> DailyProgress:
    progress.checked_in = True
    progress.completed_at = (now or datetime.now()).isoformat(timespec="seconds")
    return progress


def current_streak(progress_by_date: dict[date, DailyProgress], target_day: date) -> int:
    cursor = target_day if progress_by_date.get(target_day, DailyProgress(target_day)).checked_in else target_day - timedelta(days=1)
    total = 0
    while progress_by_date.get(cursor, DailyProgress(cursor)).checked_in:
        total += 1
        cursor -= timedelta(days=1)
    return total


def streak_stats(progress_by_date: dict[date, DailyProgress], target_day: date) -> dict[str, int]:
    checked_days = sorted(day for day, progress in progress_by_date.items() if progress.checked_in)
    longest = 0
    run = 0
    previous: date | None = None
    for day in checked_days:
        if previous is not None and day == previous + timedelta(days=1):
            run += 1
        else:
            run = 1
        longest = max(longest, run)
        previous = day
    return {
        "current": current_streak(progress_by_date, target_day),
        "longest": longest,
        "completed_days": len(checked_days),
    }
