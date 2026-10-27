from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .models import DailyPlan
from .storage import resolve_workspace_path


@dataclass(frozen=True)
class UnlockResult:
    allowed: bool
    code: str
    reason: str


def validate_unlock(
    plan: DailyPlan,
    workspace_root: Path,
    *,
    today: date | None = None,
) -> UnlockResult:
    current_date = today or date.today()
    if plan.plan_date != current_date:
        return UnlockResult(False, "plan_date_mismatch", "学习计划不是今天的计划")
    if not plan.is_complete():
        return UnlockResult(False, "tasks_incomplete", "还有学习任务没有完成")
    try:
        record_path = resolve_workspace_path(workspace_root, plan.learning_record)
    except ValueError:
        return UnlockResult(False, "record_path_invalid", "学习记录路径必须位于工作区内")
    if not record_path.is_file():
        return UnlockResult(False, "record_missing", "学习记录文件不存在")
    try:
        from .records import _read_text_fallback
        record_text = _read_text_fallback(record_path)
    except OSError:
        return UnlockResult(False, "record_unreadable", "学习记录文件无法读取")
    if not record_text.strip():
        return UnlockResult(False, "record_empty", "学习记录文件不能为空")
    return UnlockResult(True, "ok", "学习任务和记录检查通过")
