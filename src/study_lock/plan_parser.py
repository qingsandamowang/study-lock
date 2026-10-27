from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

from .models import DailyPlan, LearningResource, ProjectMilestone, Task


_DATE_HEADING = re.compile(r"^#\s+(\d{4}-\d{2}-\d{2})(?:\s+(.*?))?\s*$")
_SECTION_HEADING = re.compile(r"^##\s+(.+?)\s*$")
_CHECKBOX = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
_LIST_ITEM = re.compile(r"^\s*-\s+(.+?)\s*$")
_RESOURCE_TITLE = re.compile(r"^\s*-\s+(?!\[[ xX]\])(.+?)\s*$")
_RESOURCE_META = re.compile(r"^\s{2,}-\s*([^:：]+)[:：]\s*(.*?)\s*$")


def _clean_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1].strip()
    return value


def _normalize_app(value: str) -> str:
    value = _clean_value(value).lower()
    if not value or "/" in value or "\\" in value:
        raise ValueError(f"invalid application name: {value!r}")
    return value


def _normalize_domain(value: str) -> str:
    value = _clean_value(value).lower().rstrip(".")
    if not value or "://" in value or "/" in value or " " in value:
        raise ValueError(f"invalid domain: {value!r}")
    return value


def _sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    headings: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = _SECTION_HEADING.match(line)
        if match:
            headings.append((match.group(1).strip(), index))

    result: dict[str, tuple[int, int]] = {}
    for position, (name, start) in enumerate(headings):
        end = headings[position + 1][1] if position + 1 < len(headings) else len(lines)
        result[name] = (start + 1, end)
    return result


def _section_lines(lines: list[str], sections: dict[str, tuple[int, int]], name: str) -> list[str]:
    if name not in sections:
        raise ValueError(f"{name} section is missing")
    start, end = sections[name]
    return lines[start:end]


def _section_lines_any(
    lines: list[str],
    sections: dict[str, tuple[int, int]],
    names: tuple[str, ...],
) -> list[str] | None:
    for name in names:
        if name in sections:
            start, end = sections[name]
            return lines[start:end]
    return None


def _optional_text(lines: list[str] | None) -> str:
    if not lines:
        return ""
    values = [line.strip() for line in lines if line.strip()]
    return "\n".join(values)


def _optional_list(lines: list[str] | None) -> list[str]:
    if not lines:
        return []
    values: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        match = _LIST_ITEM.match(line)
        if match is not None:
            values.append(match.group(1).strip())
    return values


def _parse_checkbox_tasks(lines: list[str] | None) -> list[Task]:
    if not lines:
        return []
    tasks: list[Task] = []
    for line in lines:
        if not line.strip():
            continue
        match = _CHECKBOX.match(line)
        if match is None:
            continue
        tasks.append(Task(f"workflow-{len(tasks) + 1}", match.group(2), match.group(1).lower() == "x"))
    return tasks


def _parse_resources(lines: list[str] | None, default_kind: str) -> list[LearningResource]:
    if not lines:
        return []
    resources: list[LearningResource] = []
    current: dict[str, str] | None = None
    key_map = {
        "类型": "kind",
        "路径": "location",
        "地址": "location",
        "作用": "purpose",
        "产出": "output",
        "章节": "chapters",
    }

    def flush() -> None:
        if current is None:
            return
        location = current.get("location", "").strip()
        if not current.get("title", "").strip() or not location:
            return
        resources.append(
            LearningResource(
                title=current["title"].strip(),
                kind=current.get("kind", default_kind).strip() or default_kind,
                location=location,
                purpose=current.get("purpose", "").strip(),
                output=current.get("output", "").strip(),
                chapters=current.get("chapters", "").strip(),
            )
        )

    for line in lines:
        if not line.strip():
            continue
        metadata = _RESOURCE_META.match(line)
        if metadata and current is not None:
            key = key_map.get(metadata.group(1).strip())
            if key is not None:
                current[key] = metadata.group(2).strip()
                continue
            # 未识别的元数据键（如资源标题本身含冒号）→ 回退按标题行处理，避免吞行
        title = _RESOURCE_TITLE.match(line)
        if title is not None:
            flush()
            current = {"title": title.group(1).strip(), "kind": default_kind}
            continue
    flush()
    return resources


def _parse_project_milestones(lines: list[str] | None) -> list[ProjectMilestone]:
    if not lines:
        return []
    milestones: list[ProjectMilestone] = []
    for line in lines:
        match = _CHECKBOX.match(line)
        if match is not None:
            milestones.append(ProjectMilestone(match.group(2), match.group(1).lower() == "x"))
    return milestones


def parse_plan(path: Path) -> DailyPlan:
    path = Path(path)
    # utf-8-sig: 兼容记事本保存的带 BOM 文件，否则整个计划会被判为 SAFE_CONFIG
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()

    heading = next((_DATE_HEADING.match(line) for line in lines if line.startswith("# ")), None)
    if heading is None:
        raise ValueError(f"{path}: date heading is missing")

    plan_date = date.fromisoformat(heading.group(1))
    title = (heading.group(2) or "").strip() or plan_date.isoformat()
    sections = _sections(lines)

    goal = _optional_text(_section_lines_any(lines, sections, ("今日目标",)))
    reflection_questions = _optional_list(
        _section_lines_any(lines, sections, ("复盘问题",))
    )
    workflow = _parse_checkbox_tasks(_section_lines_any(lines, sections, ("执行流程",)))
    resources: list[LearningResource] = []
    resource_sections = (
        ("论文与资料", "资料"),
        ("视频与课程", "视频"),
        ("网站与工具", "网站"),
    )
    for section_name, default_kind in resource_sections:
        resources.extend(
            _parse_resources(_section_lines_any(lines, sections, (section_name,)), default_kind)
        )
    project_milestones = _parse_project_milestones(
        _section_lines_any(lines, sections, ("项目流程",))
    )

    task_lines = _section_lines(lines, sections, "任务")
    tasks: list[Task] = []
    for line in task_lines:
        if not line.strip():
            continue
        match = _CHECKBOX.match(line)
        if match is None:
            raise ValueError(f"{path}: malformed task line in 任务 section: {line!r}")
        tasks.append(Task(f"task-{len(tasks) + 1}", match.group(2), match.group(1).lower() == "x"))
    if not tasks:
        raise ValueError(f"{path}: 任务 section has no tasks")

    app_lines = _section_lines(lines, sections, "允许的应用")
    allowed_apps = {
        _normalize_app(match.group(1))
        for line in app_lines
        if line.strip()
        for match in [_LIST_ITEM.match(line)]
        if match is not None
    }
    if any(line.strip() and _LIST_ITEM.match(line) is None for line in app_lines):
        raise ValueError(f"{path}: malformed application line")

    domain_lines = _section_lines(lines, sections, "允许的网站")
    allowed_domains = {
        _normalize_domain(match.group(1))
        for line in domain_lines
        if line.strip()
        for match in [_LIST_ITEM.match(line)]
        if match is not None
    }
    if any(line.strip() and _LIST_ITEM.match(line) is None for line in domain_lines):
        raise ValueError(f"{path}: malformed website line")

    record_lines = _section_lines(lines, sections, "学习记录")
    record_match = next((match for line in record_lines if (match := _LIST_ITEM.match(line))), None)
    if record_match is None:
        raise ValueError(f"{path}: 学习记录 section has no path")
    learning_record = _clean_value(record_match.group(1))
    if not learning_record:
        raise ValueError(f"{path}: learning record path is empty")

    return DailyPlan(
        plan_date,
        title,
        tasks,
        allowed_apps,
        allowed_domains,
        learning_record,
        goal,
        reflection_questions,
        workflow,
        resources,
        project_milestones,
    )


def write_section_checkbox_state(path: Path, section_name: str, item_id: str, completed: bool) -> None:
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    sections = _sections([line.rstrip("\r\n") for line in lines])
    if section_name not in sections:
        raise ValueError(f"{path}: {section_name} section is missing")

    prefix = "workflow-" if item_id.startswith("workflow-") else "task-" if item_id.startswith("task-") else ""
    item_number = int(item_id.removeprefix(prefix)) if prefix else 0
    if item_number <= 0:
        raise ValueError(f"invalid item id: {item_id!r}")

    start, end = sections[section_name]
    current_number = 0
    target_index: int | None = None
    for index in range(start, end):
        if _CHECKBOX.match(lines[index].rstrip("\r\n")):
            current_number += 1
            if current_number == item_number:
                target_index = index
                break
    if target_index is None:
        raise ValueError(f"unknown item id: {item_id!r}")

    original = raw
    shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
    line = lines[target_index]
    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    content = line.rstrip("\r\n")
    updated = re.sub(
        r"^(\s*-\s+\[)[ xX](\])",
        rf"\g<1>{'x' if completed else ' '}\g<2>",
        content,
    )
    lines[target_index] = updated + newline
    out = "".join(lines)
    if raw.startswith(b"\xef\xbb\xbf"):
        out = "\ufeff" + out
    path.write_bytes(out.encode("utf-8"))
    if path.read_bytes() == original and completed:
        raise RuntimeError(f"failed to update task state in {path}")


def write_task_state(path: Path, task_id: str, completed: bool) -> None:
    write_section_checkbox_state(path, "任务", task_id, completed)
