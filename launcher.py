from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


STUDY_LOCK_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = STUDY_LOCK_DIR.parent
FROZEN_MARKER = STUDY_LOCK_DIR / "runtime" / "frozen.marker"
sys.path.insert(0, str(STUDY_LOCK_DIR / "src"))

from study_lock.cli import main as cli_main


def frozen_notice() -> int:
    """已冻结：静默退出，不在开机或误启动时显示提示窗口。"""
    return 0


def build_launch_args(
    workspace_root: Path = WORKSPACE_ROOT,
    *,
    current_date: date | None = None,
) -> list[str]:
    current_date = current_date or date.today()
    workspace_root = Path(workspace_root)
    daily_dir = workspace_root / "study-plans/daily"
    plan = daily_dir / f"{current_date.isoformat()}.md"
    launch_mode = "reminder"
    selected_date = current_date

    if not plan.exists():
        future_plans: list[tuple[date, Path]] = []
        past_plans: list[tuple[date, Path]] = []
        for candidate in daily_dir.glob("*.md"):
            try:
                candidate_date = date.fromisoformat(candidate.stem)
            except ValueError:
                continue
            if candidate_date > current_date:
                future_plans.append((candidate_date, candidate))
            elif candidate_date < current_date:
                past_plans.append((candidate_date, candidate))

        if future_plans:
            selected_date, plan = min(future_plans, key=lambda item: item[0])
            launch_mode = "reminder"
        elif past_plans:
            selected_date, plan = max(past_plans, key=lambda item: item[0])
            launch_mode = "reminder"

    return [
        "ui",
        "--mode",
        launch_mode,
        "--plan",
        str(plan),
        "--workspace",
        str(workspace_root),
        "--date",
        selected_date.isoformat(),
    ]


if __name__ == "__main__":
    if FROZEN_MARKER.exists():
        raise SystemExit(frozen_notice())
    raise SystemExit(cli_main(build_launch_args()))
