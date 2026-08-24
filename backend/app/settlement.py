"""
RecoverOS Settlement Verification
Matches incoming payment.captured webhooks to recovery records.
Handles settlement timeouts for unresolved records.
"""

from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models import PaymentFailureRecord, AuditTrailEntry
from app.state_machine import transition_state, log_audit
from app.config import SETTLEMENT_TIMEOUT_MINUTES
from app.websocket_manager import manager


async def handle_payment_captured(db: Session, payment_id: str, webhook_data: dict = None) -> dict:
    """
    Process a payment.captured webhook event.
    Matches payment_id → transitions state to RECOVERED → updates metrics.
    """
    record = db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.payment_id == payment_id
    ).first()

    if not record:
        return {"status": "not_found", "payment_id": payment_id}

    if record.recovery_state == "RECOVERED":
        return {"status": "already_recovered", "payment_id": payment_id}

    if record.recovery_state in ("INTERVENING", "DIAGNOSED"):
        await transition_state(
            db, record,
            to_state="RECOVERED",
            actor="system",
            details=f"Payment captured via Razorpay webhook. "
                    f"Amount: ₹{record.amount / 100:,.2f}. "
                    f"Recovery channel: {record.recovery_channel}",
        )

        # Broadcast metric update
        try:
            await manager.send_metric_update({
                "event": "payment_recovered",
                "payment_id": payment_id,
                "amount": record.amount,
                "failure_class": record.failure_class,
            })
        except Exception:
            pass

        return {
            "status": "recovered",
            "payment_id": payment_id,
            "amount": record.amount,
            "failure_class": record.failure_class,
        }

    return {
        "status": "invalid_state",
        "payment_id": payment_id,
        "current_state": record.recovery_state,
    }


async def handle_invoice_paid(db: Session, invoice_id: str, webhook_data: dict = None) -> dict:
    """
    Process an invoice.paid webhook event for B2B records.
    """
    record = db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.invoice_id == invoice_id
    ).first()

    if not record:
        return {"status": "not_found", "invoice_id": invoice_id}

    if record.recovery_state in ("INTERVENING", "DIAGNOSED"):
        await transition_state(
            db, record,
            to_state="RECOVERED",
            actor="system",
            details=f"Invoice {invoice_id} paid. B2B receivable recovered.",
        )
        return {"status": "recovered", "invoice_id": invoice_id}

    return {"status": "invalid_state", "invoice_id": invoice_id}


async def check_settlement_timeouts(db: Session) -> list:
    """
    Background task: check all INTERVENING records older than SETTLEMENT_TIMEOUT_MINUTES.
    Transitions timed-out records to FAILED_STOPPED.
    """
    timeout_threshold = datetime.now(timezone.utc) - timedelta(minutes=SETTLEMENT_TIMEOUT_MINUTES)

    stale_records = db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.recovery_state == "INTERVENING",
        PaymentFailureRecord.updated_at < timeout_threshold,
    ).all()

    timed_out = []
    for record in stale_records:
        await transition_state(
            db, record,
            to_state="FAILED_STOPPED",
            actor="system",
            details=f"Settlement timeout: No payment.captured webhook received within "
                    f"{SETTLEMENT_TIMEOUT_MINUTES} minutes. Record auto-closed.",
        )
        timed_out.append(record.payment_id)

    return timed_out
