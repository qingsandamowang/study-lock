from study_lock.models import Task
from study_lock.timer import (
    FocusStage,
    format_remaining,
    initial_timer_state,
    parse_stage_duration,
    start_timer,
    tick_timer,
)


def test_parse_stage_duration_supports_full_width_and_ascii_parentheses():
    assert parse_stage_duration("步骤 1（10 分钟）：阅读") == 600
    assert parse_stage_duration("step 2", default_seconds=90) == 90


def test_timer_ticks_down_and_auto_starts_next_stage():
    stages = [FocusStage("Read", 2), FocusStage("Code", 5)]
    state = start_timer(initial_timer_state(stages))

    state, finished = tick_timer(state, stages)
    assert (state.stage_index, state.remaining_seconds, state.running, finished) == (0, 1, True, False)
    state, finished = tick_timer(state, stages)
    assert (state.stage_index, state.remaining_seconds, state.running, finished) == (1, 5, True, True)


def test_timer_stops_after_last_stage_and_never_goes_negative():
    stages = [FocusStage("Only", 1)]
    state, finished = tick_timer(start_timer(initial_timer_state(stages)), stages)

    assert (state.stage_index, state.remaining_seconds, state.running, finished) == (0, 0, False, True)
    assert tick_timer(state, stages)[0].remaining_seconds == 0


def test_format_remaining_is_stable():
    assert format_remaining(0) == "00:00"
    assert format_remaining(65) == "01:05"
