from __future__ import annotations

import tempfile
import re
from datetime import date
from pathlib import Path

from .plan_parser import parse_plan
from .storage import resolve_workspace_path


_PLAN_HEADING_DATE = re.compile(r"^(#\s+)\d{4}-\d{2}-\d{2}")


def sync_plan_date_heading(content: str, plan_date: date) -> str:
    """Keep the editable heading date aligned with the filename date."""
    lines = content.splitlines(keepends=True)
    for index, line in enumerate(lines):
        line_without_eol = line.rstrip("\r\n")
        if not line_without_eol.startswith("# "):
            continue
        updated = _PLAN_HEADING_DATE.sub(rf"\g<1>{plan_date.isoformat()}", line_without_eol, count=1)
        if updated == line_without_eol:
            # 标题行存在但没有日期（如用户改成 "# 学习计划"）→ 补写日期，避免保存时解析失败
            lines[index] = f"# {plan_date.isoformat()}{line_without_eol[1:]}" + line[len(line_without_eol):]
            return "".join(lines)
        lines[index] = updated + line[len(line_without_eol):]
        return "".join(lines)
    return content


def detailed_plan_template(plan_date: date, *, title: str = "学习计划") -> str:
    day = plan_date.isoformat()
    return f"""# {day} {title}

## 今日目标
今天结束时，我能够用自己的话解释核心方法，记住 3 个关键点，完成一个最小实验，并留下可复查的学习成果。

## 执行流程
- [ ] 步骤 1（10 分钟）：先读“通俗导读”，只抓住故事主线，写下 3 个记忆点
- [ ] 步骤 2（25 分钟）：按导读地图核对论文 A，只看摘要、方法、实验和结论，完成论文卡片 A
- [ ] 步骤 3（25 分钟）：用同样方法阅读论文 B，完成论文卡片 B
- [ ] 步骤 4（15 分钟）：观看指定课程片段，把论文方法改写成一张工程流程图
- [ ] 步骤 5（35 分钟）：打开项目工作区，跑通一个最小实验，保存图像、参数和结果
- [ ] 步骤 6（10 分钟）：回答自测问题，再写下明天的第一个可执行步骤

## 论文与资料
- 通俗导读（最先读，不要直接打开原论文）
  - 类型：PDF
  - 路径：请填写工作区内的导读文件名.pdf
  - 作用：用大白话解释问题、方法、结果和与就业项目的联系
  - 阅读方式：先看结论，再看方法和实验，有疑点才查原文
  - 记忆点：3 个用自己的话写出的关键句
  - 产出：一张通俗导读卡
- 主要论文 A（导读后核对）
  - 类型：PDF
  - 路径：请填写 A 论文文件名.pdf
  - 作用：只核对导读中的关键细节
  - 重点：摘要、方法、实验、结论
  - 产出：论文卡片 A
- 主要论文 B（导读后核对）
  - 类型：PDF
  - 路径：请填写 B 论文文件名.pdf
  - 作用：只核对导读中的关键细节
  - 重点：摘要、方法、实验、结论
  - 产出：论文卡片 B

## 视频与课程
- 指定课程片段
  - 类型：视频
  - 地址：https://www.youtube.com/
  - 章节：请填写具体时间段
  - 作用：补齐实验所需概念
  - 记忆点：3 个新概念

## 网站与工具
- 官方数据集或工具文档
  - 类型：网站
  - 地址：https://github.com/
  - 作用：获取数据、接口和复现实验说明

## 项目流程
- 项目产出：结果图、运行参数、可复现命令和一个改进假设
- [ ] 准备输入数据并完成可视化
- [ ] 跑通一个可复现的基线
- [ ] 保存参数、结果图和运行命令
- [ ] 写下一个可验证的改进假设

## 复盘问题
- 我能不能不看原文，用 3 句话解释今天的核心方法？
- 每篇论文分别解决了什么问题？它们的方法有什么不同？
- 哪个实验结果支持了作者的结论，为什么？
- 如果把方法改成工业视觉项目，输入、输出和评价指标分别是什么？

## 允许的应用
- `Codex.exe`
- `chrome.exe`
- `Code.exe`
- `WINWORD.EXE`
- `AcroRd32.exe`

## 允许的网站
- chatgpt.com
- openai.com
- github.com
- youtube.com

## 任务
- [ ] 完成今日学习包并填写学习记录

## 学习记录
- `learning-records/{day}.md`
"""


def save_plan(workspace_root: Path, plan_date: date, content: str) -> Path:
    root = Path(workspace_root)
    plan_dir = resolve_workspace_path(root, "study-plans/daily")
    plan_dir.mkdir(parents=True, exist_ok=True)
    path = plan_dir / f"{plan_date.isoformat()}.md"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".md",
            prefix=f".{path.stem}-",
            dir=plan_dir,
            delete=False,
        ) as handle:
            handle.write(content)
            temporary_path = Path(handle.name)
        parsed = parse_plan(temporary_path)
        if parsed.plan_date != plan_date:
            raise ValueError(
                f"plan date {parsed.plan_date.isoformat()} does not match "
                f"requested date {plan_date.isoformat()}"
            )
        temporary_path.replace(path)
        return path
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
