from __future__ import annotations

from dataclasses import dataclass


RECOVERY_PHRASE = "I ACCEPT RECOVERY"


@dataclass(frozen=True)
class RecoveryGate:
    started_at: float
    delay_seconds: float = 60.0

    def ready(self, *, now: float) -> bool:
        return now - self.started_at >= self.delay_seconds

    def confirm(self, phrase: str, *, now: float) -> bool:
        if not self.ready(now=now):
            raise ValueError("recovery countdown is not complete")
        if phrase.strip() != RECOVERY_PHRASE:
            raise ValueError("recovery confirmation phrase is invalid")
        return True
