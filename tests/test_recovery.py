import pytest

from study_lock.recovery import RecoveryGate


def test_recovery_requires_countdown_and_confirmation_phrase():
    gate = RecoveryGate(started_at=100.0, delay_seconds=60.0)

    assert gate.ready(now=159.9) is False
    assert gate.ready(now=160.0) is True
    with pytest.raises(ValueError, match="confirmation"):
        gate.confirm("wrong", now=160.0)
    assert gate.confirm("I ACCEPT RECOVERY", now=160.0) is True
