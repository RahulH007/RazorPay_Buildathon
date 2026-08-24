"""
RecoverOS Metrics Routes
GET /api/metrics/dashboard — Aggregated dashboard metrics
"""

from fastapi import APIRouter

from app.database import SessionLocal
from app.models import PaymentFailureRecord, AuditTrailEntry, BatchRun
from sqlalchemy import func

router = APIRouter()


@router.get("/metrics/dashboard")
async def get_dashboard_metrics():
    """
    Aggregated dashboard metrics:
    Total GMV, Recovered GMV, Recovery Rate, Channel Cost, Net ROI,
    Cost per Recovery, per-class breakdown.
    """
    db = SessionLocal()
    try:
        # Get all records
        records = db.query(PaymentFailureRecord).all()

        if not records:
            return {
                "total_records": 0,
                "total_gmv": 0,
                "recovered_gmv": 0,
                "recovery_rate": 0.0,
                "total_channel_cost": 0.0,
                "net_roi": 0.0,
                "cost_per_recovery": 0.0,
                "recovered_count": 0,
                "failed_count": 0,
                "in_progress_count": 0,
                "class_breakdown": [],
                "records": [],
            }

        total_records = len(records)
        total_gmv = sum(r.amount for r in records)
        recovered = [r for r in records if r.recovery_state == "RECOVERED"]
        failed = [r for r in records if r.recovery_state == "FAILED_STOPPED"]
        in_progress = [r for r in records if r.recovery_state in ("INGESTED", "DIAGNOSED", "INTERVENING")]

        recovered_gmv = sum(r.amount for r in recovered)
        recovered_count = len(recovered)

        # Total channel cost from audit trail
        total_channel_cost = db.query(func.sum(AuditTrailEntry.cost_incurred_inr)).scalar() or 0.0

        recovery_rate = (recovered_count / total_records * 100) if total_records > 0 else 0
        net_roi = (recovered_gmv / 100) - total_channel_cost  # Convert paise to INR
        cost_per_recovery = total_channel_cost / max(recovered_count, 1)

        # Per-class breakdown
        class_data = {}
        for record in records:
            cls = record.failure_class or "UNCLASSIFIED"
            if cls not in class_data:
                class_data[cls] = {
                    "failure_class": cls,
                    "total_count": 0,
                    "recovered_count": 0,
                    "total_gmv": 0,
                    "recovered_gmv": 0,
                    "channel_cost": 0.0,
                }
            class_data[cls]["total_count"] += 1
            class_data[cls]["total_gmv"] += record.amount
            if record.recovery_state == "RECOVERED":
                class_data[cls]["recovered_count"] += 1
                class_data[cls]["recovered_gmv"] += record.amount

        for cls_info in class_data.values():
            tc = cls_info["total_count"]
            rc = cls_info["recovered_count"]
            cls_info["recovery_rate"] = round((rc / tc * 100) if tc > 0 else 0, 1)

        # Serialize records for the frontend
        records_list = [
            {
                "payment_id": r.payment_id,
                "amount": r.amount,
                "currency": r.currency,
                "method": r.method,
                "customer_name": r.customer_name,
                "customer_phone": r.customer_phone,
                "error_reason": r.error_reason,
                "error_description": r.error_description,
                "failure_class": r.failure_class,
                "recovery_state": r.recovery_state,
                "recovery_channel": r.recovery_channel,
                "subscription_id": r.subscription_id,
                "invoice_id": r.invoice_id,
            }
            for r in records
        ]

        return {
            "total_records": total_records,
            "total_gmv": total_gmv,
            "recovered_gmv": recovered_gmv,
            "recovery_rate": round(recovery_rate, 1),
            "total_channel_cost": round(total_channel_cost, 2),
            "net_roi": round(net_roi, 2),
            "cost_per_recovery": round(cost_per_recovery, 2),
            "recovered_count": recovered_count,
            "failed_count": len(failed),
            "in_progress_count": len(in_progress),
            "class_breakdown": list(class_data.values()),
            "records": records_list,
        }
    finally:
        db.close()
