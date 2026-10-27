from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from .storage import atomic_write_json


class LockState(StrEnum):
    SAFE_CONFIG = "SAFE_CONFIG"
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"
    RECOVERY = "RECOVERY"


@dataclass(frozen=True)
class RuntimeState:
    current_date: date
    status: LockState
    plan_path: str | None = None


def save_state(path: Path, state: RuntimeState) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "current_date": state.current_date.isoformat(),
        "status": state.status.value,
        "plan_path": state.plan_path,
    }
    atomic_write_json(path, payload)


def load_state(path: Path, default_date: date | None = None) -> RuntimeState:
    fallback_date = default_date or date.today()
    path = Path(path)
    if not path.is_file():
        return RuntimeState(fallback_date, LockState.SAFE_CONFIG)
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return RuntimeState(
            date.fromisoformat(payload["current_date"]),
            LockState(payload["status"]),
            payload.get("plan_path"),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return RuntimeState(fallback_date, LockState.SAFE_CONFIG)


def append_event(path: Path, event: str, data: dict[str, Any] | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "event": event,
        "data": data or {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
