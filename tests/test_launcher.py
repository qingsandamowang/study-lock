from datetime import date
from pathlib import Path

from launcher import build_launch_args, frozen_notice


def test_frozen_launcher_is_silent():
    assert frozen_notice() == 0


def test_launcher_selects_today_plan_and_workspace(tmp_path: Path):
    args = build_launch_args(tmp_path, current_date=date(2026, 7, 28))

    assert args[0:2] == ["ui", "--mode"]
    assert args[2] == "reminder"
    assert args[args.index("--plan") + 1] == str(
        tmp_path / "study-plans/daily/2026-07-28.md"
    )
    assert args[args.index("--workspace") + 1] == str(tmp_path)


def test_launcher_previews_nearest_future_plan_when_today_is_missing(tmp_path: Path):
    daily = tmp_path / "study-plans" / "daily"
    daily.mkdir(parents=True)
    future_plan = daily / "2026-07-28.md"
    future_plan.write_text("# 明日计划\n", encoding="utf-8")

    args = build_launch_args(tmp_path, current_date=date(2026, 7, 27))

    assert args[2] == "reminder"
    assert args[args.index("--plan") + 1] == str(future_plan)
    assert args[args.index("--date") + 1] == "2026-07-28"


def test_launcher_previews_latest_existing_plan_when_today_and_future_are_missing(tmp_path: Path):
    daily = tmp_path / "study-plans" / "daily"
    daily.mkdir(parents=True)
    older_plan = daily / "2026-07-28.md"
    older_plan.write_text("# 2026-07-28 学习计划\n", encoding="utf-8")

    args = build_launch_args(tmp_path, current_date=date(2026, 7, 29))

    assert args[2] == "reminder"
    assert args[args.index("--plan") + 1] == str(older_plan)
    assert args[args.index("--date") + 1] == "2026-07-28"
