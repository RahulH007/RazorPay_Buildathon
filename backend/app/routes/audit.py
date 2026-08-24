"""
RecoverOS Audit Routes
GET /api/audit/{payment_id} — Ordered audit trail entries with LLM metadata
"""

from fastapi import APIRouter, HTTPException

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

        # Get ordered audit trail
        entries = db.query(AuditTrailEntry).filter(
            AuditTrailEntry.payment_id == payment_id
        ).order_by(AuditTrailEntry.timestamp).all()

        # Calculate cumulative cost
        cumulative_cost = 0.0
        trail = []
        for entry in entries:
            cumulative_cost += entry.cost_incurred_inr or 0
            trail.append({
                "id": entry.id,
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "action": entry.action,
                "actor": entry.actor,
                "details": entry.details,
                "cost_incurred_inr": entry.cost_incurred_inr or 0,
                "cumulative_cost_inr": round(cumulative_cost, 2),
                "llm_metadata": {
                    "model": entry.llm_model,
                    "input_tokens": entry.llm_input_tokens,
                    "output_tokens": entry.llm_output_tokens,
                    "latency_ms": entry.llm_latency_ms,
                    "confidence": entry.llm_confidence,
                } if entry.llm_model else None,
            })

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
            "total_cost_inr": round(cumulative_cost, 2),
            "audit_trail": trail,
        }
    finally:
        db.close()
