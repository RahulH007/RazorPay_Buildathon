import pytest

from app.models import AuditTrailEntry
from app.recovery_actions import execute_recovery
from app.voice_pipeline import handle_dtmf_response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_class", "expected_action"),
    [
        ("TRANSIENT_TECHNICAL", "RETRY_SILENT_ATTEMPT"),
        ("AUTH_FRICTION", "WHATSAPP_LINK_SENT"),
        ("MANDATE_BALANCE", "MANDATE_RESEQUENCED"),
        # B2B escalates whatsapp -> voice -> human, so step one is WhatsApp
        ("B2B_RECEIVABLE", "WHATSAPP_LINK_SENT"),
    ],
)
async def test_action_dispatch_moves_record_to_intervening(
    db_session, payment_record, failure_class, expected_action
):
    record = payment_record(
        failure_class=failure_class,
        recovery_state="DIAGNOSED",
        error_reason="invoice_overdue_15d" if failure_class == "B2B_RECEIVABLE" else "bank_technical_error",
    )
    db_session.add(record)
    db_session.commit()

    result = await execute_recovery(db_session, record)

    actions = [
        entry.action
        for entry in db_session.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == record.payment_id)
        .all()
    ]
    assert record.recovery_state == "INTERVENING"
    assert result["action"] in {"silent_retry", "whatsapp_link", "mandate_resequence", "voice_recovery"}
    assert expected_action in actions


@pytest.mark.asyncio
async def test_hard_decline_is_blocked_by_fraud_guard(db_session, payment_record):
    record = payment_record(
        failure_class="HARD_DECLINE",
        recovery_state="DIAGNOSED",
        error_reason="compliance_violation",
    )
    db_session.add(record)
    db_session.commit()

    result = await execute_recovery(db_session, record)

    assert result["action"] == "declined"
    assert result["reason_code"] == "HARD_DECLINE"
    assert "zero customer outreach" in result["reason"].lower()
    assert record.recovery_state == "FAILED_STOPPED"

    # The refusal must be on the ledger, not merely returned to the caller.
    actions = [
        e.action
        for e in db_session.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == record.payment_id)
        .all()
    ]
    assert "POLICY_DECLINED_HARD_DECLINE" in actions


@pytest.mark.asyncio
async def test_voice_dtmf_opt_out_stops_active_record(db_session, payment_record):
    record = payment_record(
        failure_class="B2B_RECEIVABLE",
        recovery_state="INTERVENING",
        recovery_channel="hinglish_voice",
    )
    db_session.add(record)
    db_session.commit()

    result = await handle_dtmf_response(db_session, record, "9")

    assert result["response"] == "opt_out"
    assert record.recovery_state == "FAILED_STOPPED"
