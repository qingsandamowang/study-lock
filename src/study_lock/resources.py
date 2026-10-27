from __future__ import annotations

import os
import re
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .models import LearningResource
from .storage import resolve_workspace_path


@dataclass(frozen=True)
class ResourceOpenResult:
    ok: bool
    message: str


def resolve_resource_location(workspace_root: Path, location: str) -> Path | str:
    value = str(location).strip()
    if not value:
        raise ValueError("资源位置为空")
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return Path(value).resolve()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        if not parsed.netloc:
            raise ValueError("网址缺少域名")
        return value
    if parsed.scheme:
        raise ValueError(f"不支持的资源协议：{parsed.scheme}")
    return resolve_workspace_path(workspace_root, value)


def _default_file_opener(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(str(path))
    else:
        raise OSError("当前系统没有可用的文件打开器")


def _default_folder_opener(path: Path) -> None:
    _default_file_opener(path)


def _ensure_learning_record(path: Path, workspace_root: Path, title: str) -> bool:
    workspace = Path(workspace_root).resolve()
    try:
        inside_workspace = path.resolve().is_relative_to(workspace)
    except OSError:
        inside_workspace = False
    if not inside_workspace or path.exists() or path.suffix.lower() != ".md":
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {title}\n\n"
        "## 今日完成\n- \n\n"
        "## 我真正理解的内容\n- \n\n"
        "## 实验与证据\n- \n\n"
        "## 复盘问题\n- \n\n"
        "## 明天的起点\n- \n",
        encoding="utf-8",
    )
    return True


def open_resource(
    workspace_root: Path,
    resource: LearningResource,
    *,
    file_opener: Callable[[Path], object] | None = None,
    folder_opener: Callable[[Path], object] | None = None,
    url_opener: Callable[[str], object] | None = None,
) -> ResourceOpenResult:
    # 多路径资源（分号分隔，如一个步骤对应多个视频）：逐个打开并汇总。
    # 先判断整体是否为 URL 或绝对路径：分号可能是 URL 参数或文件名的合法字符
    _loc = resource.location.strip()
    if "://" in _loc or (re.match(r"^[A-Za-z]:[\\/]", _loc) and os.path.exists(_loc)):
        parts = [_loc]
    else:
        parts = [part.strip() for part in re.split(r"[；;]", _loc) if part.strip()]
    if len(parts) > 1:
        opened, failed = 0, []
        for loc in parts:
            sub = LearningResource(
                title=resource.title,
                kind=resource.kind,
                location=loc,
                purpose=resource.purpose,
                output=resource.output,
                chapters=resource.chapters,
            )
            result = open_resource(
                workspace_root, sub,
                file_opener=file_opener, folder_opener=folder_opener, url_opener=url_opener,
            )
            if result.ok:
                opened += 1
            else:
                failed.append(result.message)
        if opened:
            summary = f"已打开 {opened}/{len(parts)} 项：{resource.title}"
            if failed:
                summary += f"（失败：{failed[0]}）"
            return ResourceOpenResult(True, summary)
        return ResourceOpenResult(False, f"无法打开 {resource.title}：{failed[0] if failed else '路径为空'}")
    try:
        target = resolve_resource_location(workspace_root, resource.location)
        if isinstance(target, str):
            (url_opener or webbrowser.open)(target)
            return ResourceOpenResult(True, f"已打开：{resource.title}")
        if not target.exists() and isinstance(target, Path) and resource.kind == "记录":
            _ensure_learning_record(target, workspace_root, resource.title)
        if not target.exists():
            return ResourceOpenResult(False, f"资源不存在：{target}")
        opener = folder_opener if target.is_dir() else file_opener
        (opener or (_default_folder_opener if target.is_dir() else _default_file_opener))(target)
        return ResourceOpenResult(True, f"已打开：{resource.title}")
    except ValueError as exc:
        message = "资源路径必须位于学习工作区内" if "path must stay inside workspace" in str(exc) else str(exc)
        return ResourceOpenResult(False, f"无法打开 {resource.title}：{message}")
    except (OSError, RuntimeError) as exc:
        return ResourceOpenResult(False, f"无法打开 {resource.title}：{exc}")
