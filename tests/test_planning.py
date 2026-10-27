from datetime import date
from pathlib import Path

from study_lock.plan_parser import parse_plan
from study_lock.planning import save_plan, detailed_plan_template, sync_plan_date_heading


def test_detailed_plan_template_has_ordered_steps_and_reflection_prompts():
    content = detailed_plan_template(date(2026, 7, 29), title="论文精读与实验")

    assert "# 2026-07-29 论文精读与实验" in content
    assert "## 今日目标" in content
    assert "## 执行流程" in content
    assert "## 论文与资料" in content
    assert "## 视频与课程" in content
    assert "## 网站与工具" in content
    assert "## 项目流程" in content
    assert "## 复盘问题" in content
    assert "- [ ] 步骤 1" in content
    assert "- [ ] 步骤 2" in content
    assert "## 学习记录" in content


    assert "通俗导读" in content
    assert "记忆点" in content
    assert "自测问题" in content
    assert "项目产出" in content


def test_save_plan_validates_and_writes_a_parseable_daily_plan(tmp_path: Path):
    content = detailed_plan_template(date(2026, 7, 30))

    path = save_plan(tmp_path, date(2026, 7, 30), content)

    assert path == tmp_path / "study-plans" / "daily" / "2026-07-30.md"
    assert parse_plan(path).plan_date == date(2026, 7, 30)


def test_save_plan_rejects_a_plan_for_the_wrong_date(tmp_path: Path):
    content = detailed_plan_template(date(2026, 7, 30))

    try:
        save_plan(tmp_path, date(2026, 7, 31), content)
    except ValueError as exc:
        assert "date" in str(exc).lower()
    else:
        raise AssertionError("save_plan should reject a mismatched plan date")


def test_sync_plan_date_heading_updates_editor_content_before_save(tmp_path: Path):
    content = detailed_plan_template(date(2026, 7, 30), title="论文精读")

    synced = sync_plan_date_heading(content, date(2026, 7, 29))

    assert synced.startswith("# 2026-07-29 论文精读")
    path = save_plan(tmp_path, date(2026, 7, 29), synced)
    assert parse_plan(path).plan_date == date(2026, 7, 29)
