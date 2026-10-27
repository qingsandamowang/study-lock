from __future__ import annotations

import shutil
from pathlib import Path

from .models import DailyPlan
from .storage import resolve_workspace_path


_USER_NOTE_SECTIONS = {"今日完成", "我真正理解的内容", "实验与证据", "明天的起点"}


def record_path(workspace_root: Path, plan: DailyPlan) -> Path:
    return resolve_workspace_path(workspace_root, plan.learning_record)


def record_template(plan: DailyPlan) -> str:
    task_lines = "\n".join(
        f"- [{'x' if task.completed else ' '}] {task.label}" for task in plan.tasks
    )
    question_lines = "\n".join(f"- {question}" for question in plan.reflection_questions)
    if not question_lines:
        question_lines = "- 今天最重要的一个收获是什么？"
    return f"""# {plan.plan_date.isoformat()} 学习成果

## 今日目标
{plan.goal or "请用一句话写下今天完成学习后应达到的状态。"}

## 任务完成情况
{task_lines}

## 今天完成了什么
<!-- 用 3-5 条要点记录：读了什么、做了什么、产出了什么。 -->
-

## 我真正理解的内容
<!-- 不看资料，用自己的话写出核心概念、方法或代码流程。 -->
-

## 实验与证据
<!-- 写清输入、操作、结果、截图或文件路径；没有实验就说明原因。 -->
-

## 复盘问题
{question_lines}

## 明天的起点
<!-- 明天打开电脑后，第一步具体做什么？控制在一句话。 -->
-

## 疑问与待查资料
-
"""


def ensure_record(workspace_root: Path, plan: DailyPlan) -> Path:
    path = record_path(workspace_root, plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(record_template(plan), encoding="utf-8")
    return path


def _read_text_fallback(path: Path) -> str:
    """多编码回退读取：UTF-8 → GBK → UTF-16 → 替换符（兼容记事本/WPS ANSI 保存）"""
    raw = path.read_bytes()
    for enc in ("utf-8", "gbk", "utf-16", "cp936"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def record_has_user_content(path: Path) -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    try:
        lines = _read_text_fallback(path).splitlines()
    except OSError:
        return False
    section: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            section = stripped[3:].strip()
            continue
        if section not in _USER_NOTE_SECTIONS or not stripped or stripped.startswith("<!--"):
            continue
        if stripped.startswith("-"):
            stripped = stripped[1:].strip()
        if stripped and not stripped.startswith("<!--"):
            return True
    return False


def save_record(path: Path, content: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(content, encoding="utf-8")
    return path
