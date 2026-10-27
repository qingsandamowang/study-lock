from pathlib import Path

import pytest

from study_lock.plan_parser import parse_plan, write_section_checkbox_state, write_task_state


PLAN_TEXT = """# 2026-07-28 学习计划

## 任务
- [ ] Read abstract
- [x] Write card

## 允许的应用
- `Code.exe`

## 允许的网站
- chatgpt.com
- `Pytorch.org`

## 学习记录
- `learning-records/2026-07-28.md`
"""


def test_parse_plan_preserves_task_order_and_normalizes_allowlists(tmp_path: Path):
    plan_path = tmp_path / "2026-07-28.md"
    plan_path.write_text(PLAN_TEXT, encoding="utf-8")

    plan = parse_plan(plan_path)

    assert [task.task_id for task in plan.tasks] == ["task-1", "task-2"]
    assert [task.label for task in plan.tasks] == ["Read abstract", "Write card"]
    assert [task.completed for task in plan.tasks] == [False, True]
    assert plan.allowed_apps == {"code.exe"}
    assert plan.allowed_domains == {"chatgpt.com", "pytorch.org"}
    assert plan.learning_record == "learning-records/2026-07-28.md"


def test_parse_plan_reads_optional_goal_and_reflection_questions(tmp_path: Path):
    plan_path = tmp_path / "2026-07-29.md"
    plan_path.write_text(
        "# 2026-07-29 视觉算法学习\n\n"
        "## 今日目标\n"
        "完成一张论文卡片，并跑通一个可复现实验。\n\n"
        "## 任务\n"
        "- [ ] 步骤 1（10 分钟）：阅读方法部分\n\n"
        "## 复盘问题\n"
        "- 我能否不用看资料解释核心方法？\n"
        "- 哪个实验结果支持了作者结论？\n\n"
        "## 允许的应用\n"
        "- `Code.exe`\n\n"
        "## 允许的网站\n"
        "- chatgpt.com\n\n"
        "## 学习记录\n"
        "- `learning-records/2026-07-29.md`\n",
        encoding="utf-8",
    )

    plan = parse_plan(plan_path)

    assert plan.goal == "完成一张论文卡片，并跑通一个可复现实验。"
    assert plan.reflection_questions == [
        "我能否不用看资料解释核心方法？",
        "哪个实验结果支持了作者结论？",
    ]


def test_parse_plan_reads_workflow_resources_and_project_milestones(tmp_path: Path):
    plan_path = tmp_path / "2026-07-29.md"
    plan_path.write_text(
        "# 2026-07-29 内容包\n\n"
        "## 执行流程\n"
        "- [ ] 步骤 1（10 分钟）：定义问题\n"
        "- [x] 步骤 2（20 分钟）：完成论文卡片\n\n"
        "## 论文与资料\n"
        "- 文档 A：论文\n"
        "  - 类型：PDF\n"
        "  - 路径：paper.pdf\n"
        "  - 作用：理解方法\n"
        "  - 产出：论文卡片 A\n\n"
        "- 文档 B：论文\n"
        "  - 类型：PDF\n"
        "  - 路径：paper-b.pdf\n\n"
        "## 视频与课程\n"
        "- 红外热成像入门\n"
        "  - 类型：视频\n"
        "  - 地址：https://example.com/video\n"
        "  - 章节：10:00-22:00\n\n"
        "## 网站与工具\n"
        "- MVTec AD\n"
        "  - 类型：网站\n"
        "  - 地址：https://www.mvtec.com/\n"
        "  - 作用：查看数据集说明\n\n"
        "## 项目流程\n"
        "- [ ] 读取样本并可视化\n"
        "- [x] 跑通缺陷检测基线\n\n"
        "## 任务\n- [ ] 兼容旧任务\n\n"
        "## 允许的应用\n- `Code.exe`\n\n"
        "## 允许的网站\n- example.com\n\n"
        "## 学习记录\n- `record.md`\n",
        encoding="utf-8",
    )

    plan = parse_plan(plan_path)

    assert [task.label for task in plan.workflow] == [
        "步骤 1（10 分钟）：定义问题",
        "步骤 2（20 分钟）：完成论文卡片",
    ]
    assert [task.completed for task in plan.workflow] == [False, True]
    assert plan.resources[0].title == "文档 A：论文"
    assert plan.resources[0].kind == "PDF"
    assert plan.resources[0].location == "paper.pdf"
    assert plan.resources[0].purpose == "理解方法"
    assert plan.resources[0].output == "论文卡片 A"
    assert len(plan.resources) == 4
    assert plan.resources[1].title == "文档 B：论文"
    assert plan.resources[1].location == "paper-b.pdf"
    assert plan.resources[2].chapters == "10:00-22:00"
    assert plan.project_milestones[1].completed is True


def test_write_task_state_updates_only_the_selected_checkbox_and_creates_backup(
    tmp_path: Path,
):
    plan_path = tmp_path / "2026-07-28.md"
    plan_path.write_text(PLAN_TEXT, encoding="utf-8")

    write_task_state(plan_path, "task-1", True)

    updated = plan_path.read_text(encoding="utf-8")
    assert "- [x] Read abstract" in updated
    assert "- [x] Write card" in updated
    assert plan_path.with_suffix(".md.bak").read_text(encoding="utf-8") == PLAN_TEXT


def test_parse_plan_rejects_missing_tasks(tmp_path: Path):
    plan_path = tmp_path / "bad.md"
    plan_path.write_text("# 2026-07-28\n\n## 任务\n", encoding="utf-8")

    with pytest.raises(ValueError, match="任务"):
        parse_plan(plan_path)


def test_write_section_checkbox_state_updates_a_workflow_step(tmp_path: Path):
    plan_path = tmp_path / "2026-07-29.md"
    plan_path.write_text(
        "# 2026-07-29 学习计划\n\n"
        "## 执行流程\n"
        "- [ ] 步骤 1\n"
        "- [ ] 步骤 2\n\n"
        "## 任务\n- [ ] 完成学习\n\n"
        "## 允许的应用\n- `Code.exe`\n\n"
        "## 允许的网站\n- example.com\n\n"
        "## 学习记录\n- `record.md`\n",
        encoding="utf-8",
    )

    write_section_checkbox_state(plan_path, "执行流程", "workflow-2", True)

    content = plan_path.read_text(encoding="utf-8")
    assert "- [ ] 步骤 1" in content
    assert "- [x] 步骤 2" in content
    assert plan_path.with_suffix(".md.bak").is_file()
