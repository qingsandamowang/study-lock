from pathlib import Path

import pytest

from study_lock.storage import resolve_workspace_path


def test_resolve_workspace_path_stays_inside_workspace(tmp_path: Path):
    resolved = resolve_workspace_path(tmp_path, "learning-records/today.md")

    assert resolved == (tmp_path / "learning-records/today.md").resolve()


def test_resolve_workspace_path_rejects_escape(tmp_path: Path):
    with pytest.raises(ValueError, match="workspace"):
        resolve_workspace_path(tmp_path, "../outside.txt")
