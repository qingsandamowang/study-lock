from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Task


@dataclass(frozen=True)
class FocusStage:
    label: str
    seconds: int


@dataclass(frozen=True)
class TimerState:
    stage_index: int
    remaining_seconds: int
    running: bool = False


_DURATION_RE = re.compile(r"[（(]\s*(\d+)\s*(?:分钟|minutes?)\s*[）)]", re.IGNORECASE)


def parse_stage_duration(label: str, *, default_seconds: int = 25 * 60) -> int:
    match = _DURATION_RE.search(label)
    if match is None:
        return max(1, int(default_seconds))
    return max(1, int(match.group(1)) * 60)


def build_focus_stages(tasks: list[Task], *, default_seconds: int = 25 * 60) -> list[FocusStage]:
    stages = [FocusStage(task.label, parse_stage_duration(task.label, default_seconds=default_seconds)) for task in tasks]
    return stages or [FocusStage("当前学习", default_seconds)]


def initial_timer_state(stages: list[FocusStage]) -> TimerState:
    if not stages:
        return TimerState(0, 0, False)
    return TimerState(0, max(0, stages[0].seconds), False)


def start_timer(state: TimerState) -> TimerState:
    return TimerState(state.stage_index, state.remaining_seconds, state.remaining_seconds > 0)


def pause_timer(state: TimerState) -> TimerState:
    return TimerState(state.stage_index, state.remaining_seconds, False)


def reset_timer(stages: list[FocusStage]) -> TimerState:
    return initial_timer_state(stages)


def tick_timer(state: TimerState, stages: list[FocusStage]) -> tuple[TimerState, bool]:
    if not stages or not state.running or state.remaining_seconds <= 0:
        return TimerState(state.stage_index, max(0, state.remaining_seconds), False if state.remaining_seconds <= 0 else state.running), False
    remaining = state.remaining_seconds - 1
    if remaining > 0:
        return TimerState(state.stage_index, remaining, True), False
    next_index = state.stage_index + 1
    if next_index >= len(stages):
        return TimerState(state.stage_index, 0, False), True
    return TimerState(next_index, stages[next_index].seconds, True), True


def format_remaining(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
