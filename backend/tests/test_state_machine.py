import pytest

from app.models import AuditTrailEntry
from app.state_machine import transition_state, validate_transition


def test_valid_transitions_match_recovery_lifecycle():
    assert validate_transition("INGESTED", "DIAGNOSED") is True
    assert validate_transition("DIAGNOSED", "INTERVENING") is True
    assert validate_transition("INTERVENING", "RECOVERED") is True
    assert validate_transition("INTERVENING", "FAILED_STOPPED") is True
    assert validate_transition("RECOVERED", "INTERVENING") is False


@pytest.mark.asyncio
async def test_transition_updates_record_and_writes_audit(db_session, payment_record):
    record = payment_record()
    db_session.add(record)
    db_session.commit()

    await transition_state(
        db_session,
        record,
        "DIAGNOSED",
        actor="rule_engine",
        details="Known error code",
    )

    entry = (
        db_session.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == record.payment_id)
        .one()
    )
    assert record.recovery_state == "DIAGNOSED"
    assert entry.action == "STATE_INGESTED_TO_DIAGNOSED"
    assert entry.actor == "rule_engine"
    assert entry.details == "Known error code"


@pytest.mark.asyncio
async def test_invalid_transition_raises_value_error(db_session, payment_record):
    record = payment_record(recovery_state="RECOVERED")
    db_session.add(record)
    db_session.commit()

    with pytest.raises(ValueError, match="Invalid transition"):
        await transition_state(db_session, record, "INTERVENING")
