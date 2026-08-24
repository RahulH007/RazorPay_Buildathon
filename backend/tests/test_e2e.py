import random

import pytest

import app.recovery_simulator as simulator
from app.models import AuditTrailEntry, PaymentFailureRecord
from app.state_machine import log_audit


@pytest.mark.asyncio
async def test_recovery_batch_end_to_end(db_session, monkeypatch):
    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(simulator.asyncio, "sleep", no_sleep)
    random.seed(21)

    result = await simulator.run_batch_simulation(db_session, "batch_e2e_001")
    records = db_session.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.batch_id == "batch_e2e_001"
    ).all()

    assert result["status"] == "COMPLETED"
    assert len(records) == 50
    assert all(record.recovery_state in {"RECOVERED", "FAILED_STOPPED"} for record in records)
    assert result["recovered_gmv"] > 0

    hard_declines = [record for record in records if record.failure_class == "HARD_DECLINE"]
    assert len(hard_declines) == 4
    assert all(record.recovery_state == "FAILED_STOPPED" for record in hard_declines)

    for record in records:
        audit_count = db_session.query(AuditTrailEntry).filter(
            AuditTrailEntry.payment_id == record.payment_id
        ).count()
        assert audit_count >= 2

    opt_out_record = next(record for record in records if record.recovery_state == "FAILED_STOPPED")
    log_audit(db_session, opt_out_record, "CUSTOMER_OPT_OUT", actor="customer")
    assert db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.payment_id == opt_out_record.payment_id,
        AuditTrailEntry.action == "CUSTOMER_OPT_OUT",
    ).count() == 1
