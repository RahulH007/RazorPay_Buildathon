"""
RecoverOS Recovery Routes
GET /api/recovery/{payment_id} — Full record with audit trail
POST /api/recovery/{payment_id}/opt-out — Process customer opt-out
POST /api/recovery/{payment_id}/settle — Simulate settlement (for phone simulator)
POST /api/recovery/{payment_id}/dtmf — Handle voice DTMF response
GET /api/voice/{payment_id} — Get voice script

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from fastapi import APIRouter, HTTPException

from app import ledger
from app.consent import record_opt_out
from app.database import SessionLocal
from app.models import PaymentFailureRecord, AuditTrailEntry
from app.state_machine import transition_state, log_audit
from app.schemas import PaymentFailureResponse
from app.voice_pipeline import handle_dtmf_response
from app.llm_agent import generate_hinglish_script
from app.inbound import handle_reply

router = APIRouter()


@router.get("/recovery/{payment_id}")
async def get_recovery_record(payment_id: str):
    """Get full recovery record with audit trail."""
    db = SessionLocal()
    try:
        record = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.payment_id == payment_id
        ).first()

        if not record:
            raise HTTPException(status_code=404, detail=f"Record not found: {payment_id}")

        # Ordered by chain position, which is also chronological order
        audit_entries = db.query(AuditTrailEntry).filter(
            AuditTrailEntry.payment_id == payment_id
        ).order_by(AuditTrailEntry.sequence_no).all()

        return {
            "payment_id": record.payment_id,
            "amount": record.amount,
            "currency": record.currency,
            "method": record.method,
            "subscription_id": record.subscription_id,
            "invoice_id": record.invoice_id,
            "merchant_id": record.merchant_id,
            "customer_name": record.customer_name,
            "customer_email": record.customer_email,
            "customer_phone": record.customer_phone,
            "error_source": record.error_source,
            "error_step": record.error_step,
            "error_reason": record.error_reason,
            "error_description": record.error_description,
            "failure_class": record.failure_class,
            "recovery_state": record.recovery_state,
            "recovery_channel": record.recovery_channel,
            "batch_id": record.batch_id,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "audit_trail": [
                {
                    "id": e.id,
                    "sequence_no": e.sequence_no,
                    "entry_hash": e.entry_hash,
                    "timestamp": ledger.us_to_iso(e.timestamp_us),
                    "action": e.action,
                    "actor": e.actor,
                    "details": e.details,
                    "cost_paise": e.cost_paise,
                    "cost_inr": (e.cost_paise or 0) / 100.0,
                    "llm_model": e.llm_model,
                    "llm_input_tokens": e.llm_input_tokens,
                    "llm_output_tokens": e.llm_output_tokens,
                    "llm_latency_ms": e.llm_latency_ms,
                    "llm_confidence": e.llm_confidence,
                }
                for e in audit_entries
            ],
        }
    finally:
        db.close()


@router.post("/recovery/{payment_id}/opt-out")
async def opt_out_record(payment_id: str):
    """Process customer opt-out — immediately halt all recovery actions."""
    db = SessionLocal()
    try:
        record = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.payment_id == payment_id
        ).first()

        if not record:
            raise HTTPException(status_code=404, detail=f"Record not found: {payment_id}")

        if record.recovery_state in ("RECOVERED", "FAILED_STOPPED"):
            return {
                "status": "already_terminal",
                "payment_id": payment_id,
                "recovery_state": record.recovery_state,
                "message": "Record is already in a terminal state",
            }

        # Registry first — this is what suppresses the contact's other payments
        record_opt_out(
            db,
            phone=record.customer_phone,
            source="api",
            payment_id=record.payment_id,
            channel="all",
            batch_id=record.batch_id,
        )
        log_audit(
            db, record,
            action="CUSTOMER_OPT_OUT",
            actor="customer",
            details="Customer opted out of recovery communications (all channels)",
        )

        # Transition to FAILED_STOPPED
        await transition_state(
            db, record,
            to_state="FAILED_STOPPED",
            actor="customer",
            details="OPT_OUT: Customer requested to stop all recovery actions",
        )

        return {
            "status": "opted_out",
            "payment_id": payment_id,
            "recovery_state": "FAILED_STOPPED",
            "message": "All recovery actions halted per customer request",
            "scope": "Suppression applies to every future payment from this contact",
        }
    finally:
        db.close()


@router.post("/recovery/{payment_id}/quarantine")
async def quarantine_record(payment_id: str):
    """
    Halt recovery on a fraud signal.

    This exists because the dashboard's fraud drill previously called the
    opt-out endpoint, which writes CUSTOMER_OPT_OUT with actor="customer" - a
    system decision recorded as a customer request. Misattributing an actor in
    a ledger that exists to prove who did what is precisely the failure this
    project claims to prevent, so a fraud halt gets its own action and its own
    actor.

    Note it does NOT touch the consent registry: the customer withdrew nothing,
    and suppressing their other payments on our suspicion would be a different
    decision than the one being taken here.
    """
    db = SessionLocal()
    try:
        record = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.payment_id == payment_id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail=f"Record not found: {payment_id}")

        if record.recovery_state in ("RECOVERED", "FAILED_STOPPED"):
            return {
                "status": "already_terminal",
                "payment_id": payment_id,
                "recovery_state": record.recovery_state,
            }

        log_audit(
            db, record,
            action="FRAUD_QUARANTINE",
            actor="system",
            details=(
                "WHY_WE_DIDNT_ACT: fraud signal raised against this payment. "
                "Recovery halted pending manual review. No customer contact "
                "was made and no consent was withdrawn."
            ),
            cost_paise=0,
        )

        await transition_state(
            db, record,
            to_state="FAILED_STOPPED",
            actor="system",
            details="FRAUD_QUARANTINE: halted for manual review",
        )

        return {
            "status": "quarantined",
            "payment_id": payment_id,
            "recovery_state": "FAILED_STOPPED",
            "message": "Recovery halted on a fraud signal, pending manual review",
        }
    finally:
        db.close()


@router.post("/recovery/{payment_id}/reply")
async def receive_customer_reply(payment_id: str, payload: dict):
    """
    Accept an inbound customer message (WhatsApp reply, SMS) and act on it.

    This is the path the WhatsApp simulator drives. In live mode the same
    handler serves a provider webhook.
    """
    message = (payload or {}).get("message", "")
    if not message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    db = SessionLocal()
    try:
        record = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.payment_id == payment_id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail=f"Record not found: {payment_id}")

        result = await handle_reply(db, record, message)
        return {"payment_id": payment_id, **result}
    finally:
        db.close()


@router.post("/recovery/{payment_id}/settle")
async def simulate_settlement(payment_id: str):
    """
    Simulate a payment settlement (for the phone simulator UPI Pay flow).
    Transitions record to RECOVERED.
    """
    db = SessionLocal()
    try:
        record = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.payment_id == payment_id
        ).first()

        if not record:
            raise HTTPException(status_code=404, detail=f"Record not found: {payment_id}")

        if record.recovery_state == "RECOVERED":
            return {"status": "already_recovered", "payment_id": payment_id}

        if record.recovery_state in ("INTERVENING", "DIAGNOSED", "INGESTED"):
            # Ensure proper state for transition
            if record.recovery_state == "INGESTED":
                record.recovery_state = "DIAGNOSED"
                db.commit()
            if record.recovery_state == "DIAGNOSED":
                await transition_state(
                    db, record,
                    to_state="INTERVENING",
                    actor="system",
                    details="Phone simulator initiated payment flow",
                )

            await transition_state(
                db, record,
                to_state="RECOVERED",
                actor="system",
                details=f"Payment settled via phone simulator. Amount: ₹{record.amount / 100:,.2f}",
            )

            return {
                "status": "recovered",
                "payment_id": payment_id,
                "amount": record.amount,
                "message": "Payment successfully settled",
            }

        return {
            "status": "invalid_state",
            "payment_id": payment_id,
            "recovery_state": record.recovery_state,
        }
    finally:
        db.close()


@router.post("/recovery/{payment_id}/dtmf")
async def handle_dtmf(payment_id: str, key: str = "1"):
    """Handle DTMF response from voice call simulator."""
    db = SessionLocal()
    try:
        record = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.payment_id == payment_id
        ).first()

        if not record:
            raise HTTPException(status_code=404, detail=f"Record not found: {payment_id}")

        result = await handle_dtmf_response(db, record, key)
        return result
    finally:
        db.close()


@router.get("/voice/{payment_id}")
async def get_voice_script(payment_id: str):
    """Get the Hinglish voice script for a payment record."""
    db = SessionLocal()
    try:
        record = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.payment_id == payment_id
        ).first()

        if not record:
            raise HTTPException(status_code=404, detail=f"Record not found: {payment_id}")

        script, _metadata, _rejection = await generate_hinglish_script(record)

        return {
            "payment_id": payment_id,
            "script": script,
            "customer_name": record.customer_name,
            "amount": record.amount,
            "language": "hi-IN (Hinglish)",
        }
    finally:
        db.close()
