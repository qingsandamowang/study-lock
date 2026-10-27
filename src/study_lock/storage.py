from __future__ import annotations

from pathlib import Path


def resolve_workspace_path(workspace_root: Path, relative_path: str) -> Path:
    """Resolve a user path while preventing traversal outside the workspace."""
    root = workspace_root.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("path must stay inside workspace")
    return candidate
