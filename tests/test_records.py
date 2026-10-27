from datetime import date
from pathlib import Path

from study_lock.models import DailyPlan, Task
from study_lock.records import ensure_record, record_has_user_content, save_record


def make_plan() -> DailyPlan:
    return DailyPlan(
        date(2026, 7, 29),
        "论文精读",
        [Task("task-1", "阅读方法"), Task("task-2", "完成实验")],
        {"code.exe"},
        {"github.com"},
        "learning-records/2026-07-29.md",
        "能解释核心方法并留下实验结果。",
        ["我能否不用看资料复述方法？", "下一步实验是什么？"],
    )


def test_ensure_record_creates_a_structured_record_from_the_plan(tmp_path: Path):
    path = ensure_record(tmp_path, make_plan())

    content = path.read_text(encoding="utf-8")
    assert path == tmp_path / "learning-records" / "2026-07-29.md"
    assert "能解释核心方法并留下实验结果。" in content
    assert "- [ ] 阅读方法" in content
    assert "我能否不用看资料复述方法？" in content
    assert "## 今天完成了什么" in content


def test_ensure_record_does_not_overwrite_existing_notes(tmp_path: Path):
    path = tmp_path / "learning-records" / "2026-07-29.md"
    path.parent.mkdir(parents=True)
    path.write_text("# 我的真实笔记\n", encoding="utf-8")

    assert ensure_record(tmp_path, make_plan()) == path
    assert path.read_text(encoding="utf-8") == "# 我的真实笔记\n"


def test_save_record_creates_backup_before_overwriting(tmp_path: Path):
    path = ensure_record(tmp_path, make_plan())
    original = path.read_text(encoding="utf-8")

    save_record(path, original + "\n新的结论\n")

    assert "新的结论" in path.read_text(encoding="utf-8")
    assert path.with_suffix(path.suffix + ".bak").read_text(encoding="utf-8") == original


def test_record_content_requires_a_real_learning_note(tmp_path: Path):
    path = tmp_path / "learning-records" / "2026-07-30.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# 学习记录\n\n## 今日完成\n- \n\n## 我真正理解的内容\n- \n\n## 实验与证据\n- \n\n## 明天的起点\n- \n",
        encoding="utf-8",
    )
    assert record_has_user_content(path) is False

    path.write_text(path.read_text(encoding="utf-8") + "\n今天理解了输入、处理、输出三段流程。\n", encoding="utf-8")

    assert record_has_user_content(path) is True
