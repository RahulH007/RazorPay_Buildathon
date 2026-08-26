"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest

from app.settlement import handle_invoice_paid, handle_payment_captured


@pytest.mark.asyncio
async def test_payment_captured_recovers_intervening_record(db_session, payment_record):
    record = payment_record(
        recovery_state="INTERVENING",
        failure_class="AUTH_FRICTION",
        recovery_channel="whatsapp_link",
    )
    db_session.add(record)
    db_session.commit()

    result = await handle_payment_captured(db_session, record.payment_id)

    assert result["status"] == "recovered"
    assert record.recovery_state == "RECOVERED"


@pytest.mark.asyncio
async def test_invoice_paid_recovers_matching_b2b_record(db_session, payment_record):
    record = payment_record(
        payment_id="pay_invoice_001",
        invoice_id="inv_test_001",
        recovery_state="INTERVENING",
        failure_class="B2B_RECEIVABLE",
        recovery_channel="hinglish_voice",
    )
    db_session.add(record)
    db_session.commit()

    result = await handle_invoice_paid(db_session, record.invoice_id)

    assert result["status"] == "recovered"
    assert record.recovery_state == "RECOVERED"


@pytest.mark.asyncio
async def test_captured_payment_for_unknown_record_is_not_found(db_session):
    result = await handle_payment_captured(db_session, "pay_missing")

    assert result == {"status": "not_found", "payment_id": "pay_missing"}
