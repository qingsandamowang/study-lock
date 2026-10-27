from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from study_lock.controller import StudyLockController
from study_lock.domain_rules import domain_allowed
from study_lock.plan_parser import parse_plan
from study_lock.recovery import RecoveryGate
from study_lock.resources import resolve_resource_location
from study_lock.state import LockState


def write_plan(path: Path, plan_date: str, checked: bool = False) -> None:
    marker = "x" if checked else " "
    path.write_text(
        f"# {plan_date} 学习计划\n\n"
        f"## 任务\n- [{marker}] Write card\n\n"
        "## 允许的应用\n- `Code.exe`\n\n"
        "## 允许的网站\n- chatgpt.com\n\n"
        f"## 学习记录\n- `learning-records/{plan_date}.md`\n",
        encoding="utf-8",
    )


def test_lock_unlock_and_next_day_flow(tmp_path: Path):
    today = date(2026, 7, 28)
    plan = tmp_path / "today.md"
    write_plan(plan, today.isoformat())
    record = tmp_path / "learning-records/2026-07-28.md"
    record.parent.mkdir()
    record.write_text("完成了论文卡片。", encoding="utf-8")

    controller = StudyLockController(tmp_path, plan, today=today, simulation=True)
    assert controller.start().status is LockState.LOCKED
    assert controller.request_unlock().status is LockState.LOCKED

    plan.write_text(plan.read_text(encoding="utf-8").replace("- [ ]", "- [x]"), encoding="utf-8")
    assert controller.request_unlock().status is LockState.UNLOCKED

    next_plan = tmp_path / "tomorrow.md"
    write_plan(next_plan, "2026-07-29", checked=True)
    next_record = tmp_path / "learning-records/2026-07-29.md"
    next_record.write_text("完成了明日任务。", encoding="utf-8")
    controller.next_day(next_plan, today=date(2026, 7, 29))
    assert controller.state.status is LockState.LOCKED


def test_recovery_marker_prevents_relocking_after_restart(tmp_path: Path):
    today = date(2026, 7, 28)
    plan = tmp_path / "today.md"
    write_plan(plan, today.isoformat())
    controller = StudyLockController(tmp_path, plan, today=today, simulation=True)
    assert controller.start().status is LockState.LOCKED

    gate = RecoveryGate(started_at=100.0, delay_seconds=0.0)
    state = controller.enter_recovery(gate, "I ACCEPT RECOVERY", now=100.0)
    assert state.status is LockState.RECOVERY

    restarted = StudyLockController(tmp_path, plan, today=today, simulation=True)

    assert restarted.start().status is LockState.RECOVERY


def test_real_daily_content_package_has_safe_local_resources_and_allowed_urls(tmp_path: Path):
    workspace = Path(__file__).resolve().parents[1] / "examples/demo-workspace"
    source_plan = workspace / "study-plans/daily/2026-07-28.md"
    plan_path = tmp_path / "study-plans/daily/2026-07-28.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(source_plan.read_text(encoding="utf-8"), encoding="utf-8")
    for filename in (
        "resources/example-a.md",
        "resources/example-b.md",
        "resources/quick-start.md",
    ):
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"placeholder")

    plan = parse_plan(plan_path)
    local_resources = [resource for resource in plan.resources if not resource.location.startswith("http")]
    url_resources = [resource for resource in plan.resources if resource.location.startswith("http")]

    assert len(local_resources) == 4
    assert all(Path(resolve_resource_location(tmp_path, item.location)).is_relative_to(tmp_path.resolve()) for item in local_resources)
    assert all(domain_allowed(urlparse(item.location).hostname or "", plan.allowed_domains) for item in url_resources)
