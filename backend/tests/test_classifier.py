"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest

from app.classifier import RULE_MAP, classify
from app.models import AuditTrailEntry


@pytest.mark.asyncio
async def test_known_error_codes_use_rule_engine(db_session, payment_record):
    for index, (error_reason, expected_class) in enumerate(RULE_MAP.items()):
        record = payment_record(
            payment_id=f"pay_rule_{index}",
            error_reason=error_reason,
        )
        db_session.add(record)
        db_session.commit()

        result = await classify(db_session, record)

        assert result == expected_class
        assert record.failure_class == expected_class.value
        expected_state = "FAILED_STOPPED" if expected_class.value == "HARD_DECLINE" else "DIAGNOSED"
        assert record.recovery_state == expected_state
        if expected_class.value == "HARD_DECLINE":
            assert record.recovery_channel is None
        else:
            assert record.recovery_channel is not None


@pytest.mark.asyncio
async def test_hard_decline_is_stopped_without_recovery_channel(db_session, payment_record):
    record = payment_record(
        error_reason="compliance_violation",
        error_description="Risk rule matched",
    )
    db_session.add(record)
    db_session.commit()

    await classify(db_session, record)

    actions = [
        entry.action
        for entry in db_session.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == record.payment_id)
        .all()
    ]

    assert record.failure_class == "HARD_DECLINE"
    assert record.recovery_channel is None
    assert record.recovery_state == "FAILED_STOPPED"
    assert "CLASSIFIED_HARD_DECLINE" in actions
    assert "STATE_DIAGNOSED_TO_FAILED_STOPPED" in actions
