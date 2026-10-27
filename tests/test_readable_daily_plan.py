from pathlib import Path

from study_lock.plan_parser import parse_plan


WORKSPACE = (Path(__file__).resolve().parents[1] / "examples/demo-workspace")


def test_current_daily_plan_pairs_reading_steps_with_the_matching_resources():
    plan = parse_plan(WORKSPACE / "study-plans/daily/2026-07-29.md")

    assert "通俗导读" in plan.workflow[0].label
    assert "示例文档 A" in plan.workflow[1].label
    assert "示例文档 B" in plan.workflow[2].label
    assert "导读" in plan.resources[0].title
    assert "示例文档 A" in plan.resources[1].title
    assert "快速通俗导读" in plan.resources[1].title
    assert "示例文档 B" in plan.resources[2].title
    assert "快速通俗导读" in plan.resources[2].title
    assert plan.resources[1].location == "resources/example-a.md"
    assert plan.resources[2].location == "resources/example-b.md"
    assert (WORKSPACE / plan.resources[1].location).is_file()
    assert (WORKSPACE / plan.resources[2].location).is_file()


def test_today_plan_has_an_openable_resource_for_every_step():
    plan = parse_plan(WORKSPACE / "study-plans/daily/2026-07-30.md")

    assert len(plan.resources) >= len(plan.workflow)
    assert plan.resources[3].location == "industrial-vision-lab"
    assert plan.resources[4].location == "learning-records/2026-07-30.md"
