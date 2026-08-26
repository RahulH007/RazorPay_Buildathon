"""
RecoverOS Audit Routes
GET /api/audit/{payment_id} — Ordered audit trail entries with LLM metadata

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from fastapi import APIRouter, HTTPException

from app import ledger
from app.database import SessionLocal
from app.models import AuditTrailEntry, PaymentFailureRecord

router = APIRouter()


@router.get("/audit/{payment_id}")
async def get_audit_trail(payment_id: str):
    """
    Returns the immutable, chronologically ordered audit trail for a payment.
    Each entry includes timestamp, action, actor, details, cost, and LLM metadata.
    """
    db = SessionLocal()
    try:
        # Verify record exists
        record = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.payment_id == payment_id
        ).first()

        if not record:
            raise HTTPException(status_code=404, detail=f"Record not found: {payment_id}")

        # Ordered by chain position, which is also chronological order
        entries = db.query(AuditTrailEntry).filter(
            AuditTrailEntry.payment_id == payment_id
        ).order_by(AuditTrailEntry.sequence_no).all()

        # Cumulative cost accumulates in integer paise — exact by construction
        cumulative_paise = 0
        trail = []
        for entry in entries:
            cumulative_paise += entry.cost_paise or 0
            trail.append({
                "id": entry.id,
                "sequence_no": entry.sequence_no,
                "prev_hash": entry.prev_hash,
                "entry_hash": entry.entry_hash,
                "timestamp": ledger.us_to_iso(entry.timestamp_us),
                "timestamp_us": entry.timestamp_us,
                "action": entry.action,
                "actor": entry.actor,
                "details": entry.details,
                "cost_paise": entry.cost_paise or 0,
                "cost_inr": (entry.cost_paise or 0) / 100.0,
                "cumulative_cost_paise": cumulative_paise,
                "cumulative_cost_inr": cumulative_paise / 100.0,
                "llm_metadata": {
                    "model": entry.llm_model,
                    "input_tokens": entry.llm_input_tokens,
                    "output_tokens": entry.llm_output_tokens,
                    "latency_ms": entry.llm_latency_ms,
                    "confidence": entry.llm_confidence,
                } if entry.llm_model else None,
            })

        verification = ledger.verify_payment(db, payment_id)

        return {
            "payment_id": payment_id,
            "record_summary": {
                "amount": record.amount,
                "failure_class": record.failure_class,
                "recovery_state": record.recovery_state,
                "recovery_channel": record.recovery_channel,
                "customer_name": record.customer_name,
            },
            "total_entries": len(trail),
            "total_cost_paise": cumulative_paise,
            "total_cost_inr": cumulative_paise / 100.0,
            "verification": verification.to_dict(),
            "audit_trail": trail,
        }
    finally:
        db.close()


@router.get("/audit/{payment_id}/verify")
async def verify_payment_trail(payment_id: str):
    """Recompute the hash of every entry belonging to this payment."""
    db = SessionLocal()
    try:
        exists = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.payment_id == payment_id
        ).first()
        if not exists:
            raise HTTPException(status_code=404, detail=f"Record not found: {payment_id}")

        return ledger.verify_payment(db, payment_id).to_dict()
    finally:
        db.close()
