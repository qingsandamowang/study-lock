from __future__ import annotations

from datetime import date
from pathlib import Path

from .plan_parser import parse_plan
from .recovery import RecoveryGate
from .state import LockState, RuntimeState, append_event, save_state
from .unlock import UnlockResult, validate_unlock


class StudyLockController:
    def __init__(
        self,
        workspace_root: Path,
        plan_path: Path,
        *,
        today: date | None = None,
        simulation: bool = True,
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self.plan_path = Path(plan_path)
        self.today = today or date.today()
        self.simulation = simulation
        self.plan = None
        self.state = RuntimeState(self.today, LockState.SAFE_CONFIG, str(self.plan_path))

    @property
    def state_path(self) -> Path:
        return self.workspace_root / "study-lock/runtime/state.json"

    @property
    def events_path(self) -> Path:
        return self.workspace_root / "study-lock/runtime/events.jsonl"

    @property
    def recovery_path(self) -> Path:
        return self.workspace_root / f"study-lock/runtime/recovery-{self.today.isoformat()}.marker"

    def _set_state(self, status: LockState) -> RuntimeState:
        self.state = RuntimeState(self.today, status, str(self.plan_path))
        save_state(self.state_path, self.state)
        return self.state

    def start(self) -> RuntimeState:
        if self.recovery_path.is_file():
            append_event(self.events_path, "recovery_bypass", {"date": self.today.isoformat()})
            return self._set_state(LockState.RECOVERY)
        try:
            self.plan = parse_plan(self.plan_path)
        except (OSError, ValueError) as exc:
            append_event(self.events_path, "safe_config", {"reason": str(exc)})
            return self._set_state(LockState.SAFE_CONFIG)
        if self.plan.plan_date != self.today:
            append_event(self.events_path, "safe_config", {"reason": "plan date mismatch"})
            return self._set_state(LockState.SAFE_CONFIG)
        append_event(self.events_path, "locked", {"plan": str(self.plan_path)})
        return self._set_state(LockState.LOCKED)

    def request_unlock(self) -> RuntimeState:
        if self.state.status is not LockState.LOCKED:
            return self.state
        try:
            self.plan = parse_plan(self.plan_path)
        except (OSError, ValueError) as exc:
            append_event(self.events_path, "unlock_rejected", {"reason": str(exc)})
            return self.state
        result: UnlockResult = validate_unlock(self.plan, self.workspace_root, today=self.today)
        if result.allowed:
            append_event(self.events_path, "unlocked", {"reason": result.reason})
            return self._set_state(LockState.UNLOCKED)
        append_event(self.events_path, "unlock_rejected", {"code": result.code, "reason": result.reason})
        return self.state

    def enter_recovery(self, gate: RecoveryGate, phrase: str, *, now: float) -> RuntimeState:
        gate.confirm(phrase, now=now)
        self.recovery_path.parent.mkdir(parents=True, exist_ok=True)
        self.recovery_path.write_text("recovery approved\n", encoding="utf-8")
        append_event(self.events_path, "recovery", {"reason": "user confirmed recovery"})
        return self._set_state(LockState.RECOVERY)

    def next_day(self, plan_path: Path, *, today: date) -> RuntimeState:
        self.plan_path = Path(plan_path)
        self.today = today
        self.plan = None
        return self.start()
