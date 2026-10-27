from __future__ import annotations

from pathlib import Path
import json
import os
import tempfile


def atomic_write_json(path: Path, payload: object) -> None:
    """Replace a complete JSON file; a failed write leaves the previous file intact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def resolve_workspace_path(workspace_root: Path, relative_path: str) -> Path:
    """Resolve a user path while preventing traversal outside the workspace."""
    root = workspace_root.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("path must stay inside workspace")
    return candidate
