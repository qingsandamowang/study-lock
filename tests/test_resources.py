from pathlib import Path

from study_lock.models import LearningResource
from study_lock.resources import open_resource, resolve_resource_location


def test_resolve_resource_location_keeps_local_paths_inside_workspace(tmp_path: Path):
    paper = tmp_path / "paper.pdf"
    paper.write_text("pdf placeholder", encoding="utf-8")

    assert resolve_resource_location(tmp_path, "paper.pdf") == paper.resolve()


def test_open_resource_dispatches_existing_file_to_file_opener(tmp_path: Path):
    paper = tmp_path / "paper.pdf"
    paper.write_text("pdf placeholder", encoding="utf-8")
    opened: list[Path] = []
    resource = LearningResource("论文", "PDF", "paper.pdf")

    result = open_resource(tmp_path, resource, file_opener=lambda path: opened.append(path))

    assert result.ok is True
    assert opened == [paper.resolve()]


def test_open_resource_dispatches_directory_to_folder_opener(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    opened: list[Path] = []
    resource = LearningResource("项目", "项目", "project")

    result = open_resource(tmp_path, resource, folder_opener=lambda path: opened.append(path))

    assert result.ok is True
    assert opened == [project.resolve()]


def test_open_resource_dispatches_https_to_url_opener(tmp_path: Path):
    opened: list[str] = []
    resource = LearningResource("视频", "视频", "https://example.com/video")

    result = open_resource(tmp_path, resource, url_opener=opened.append)

    assert result.ok is True
    assert opened == ["https://example.com/video"]


def test_open_resource_reports_missing_and_unsafe_locations(tmp_path: Path):
    missing = open_resource(tmp_path, LearningResource("缺失", "PDF", "missing.pdf"))
    unsafe = open_resource(tmp_path, LearningResource("越界", "PDF", "../outside.pdf"))
    unsupported = open_resource(tmp_path, LearningResource("协议", "网站", "ftp://example.com/a"))

    assert missing.ok is False and "不存在" in missing.message
    assert unsafe.ok is False and "工作区" in unsafe.message
    assert unsupported.ok is False and "协议" in unsupported.message


def test_open_resource_creates_a_missing_learning_record(tmp_path: Path):
    opened: list[Path] = []
    resource = LearningResource("学习记录", "记录", "learning-records/2026-07-30.md")

    result = open_resource(tmp_path, resource, file_opener=opened.append)

    record = tmp_path / "learning-records/2026-07-30.md"
    assert result.ok is True
    assert record.is_file()
    assert "学习记录" in record.read_text(encoding="utf-8")
    assert opened == [record.resolve()]
