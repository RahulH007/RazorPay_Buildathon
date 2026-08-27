"""
RecoverOS Metrics Routes
GET /api/metrics/dashboard — Aggregated dashboard metrics

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from fastapi import APIRouter

from app import ledger
from app.config import MERCHANT_MARGIN_PERCENT
from app.database import SessionLocal
from app.models import PaymentFailureRecord, AuditTrailEntry, BatchRun
from sqlalchemy import func

router = APIRouter()


def _ledger_summary(db) -> dict:
    """The ledger head, shaped identically for both branches below."""
    head = ledger.get_head(db)
    return {
        "head_hash": head.entry_hash if head else None,
        "entries": (head.sequence_no + 1) if head else 0,
    }


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
                "total_channel_cost_paise": 0,
                "total_channel_cost": 0.0,
                "net_roi_paise": 0,
                "net_roi": 0.0,
                "cost_per_recovery_paise": 0,
                "cost_per_recovery": 0.0,
                "recovered_count": 0,
                "failed_count": 0,
                "in_progress_count": 0,
                "class_breakdown": [],
                # These were copied from the populated branch below and left
                # referencing its locals - `treated`, `control`, `treated_rate`
                # and the rest are computed about 110 lines further down, so
                # this branch raised UnboundLocalError and the endpoint answered
                # 500 on any database with no records. A fresh clone, or `make
                # clean` followed by opening the dashboard, hit it every time.
                # It survived because nothing called this function: both
                # "exactly once" tests re-implemented the aggregation inline.
                "lift": {
                    "treated_count": 0,
                    "control_count": 0,
                    "treated_recovered": 0,
                    "control_recovered": 0,
                    "treated_rate": 0.0,
                    "control_rate": 0.0,
                    "lift_pp": 0.0,
                    "merchant_margin_percent": MERCHANT_MARGIN_PERCENT,
                    "sample_warning": (
                        "n=0 controls - too small for a reliable estimate. "
                        "See results/lift_analysis.md."
                    ),
                },
                # Read the real head rather than assuming an empty chain. The
                # ledger is append-only, so "no records" does not imply "no
                # entries", and reporting zero here would disagree with
                # verify_chain on exactly the database where someone is most
                # likely to be checking.
                "ledger": _ledger_summary(db),
                "records": [],
            }

        total_records = len(records)
        total_gmv = sum(r.amount for r in records)
        recovered = [r for r in records if r.recovery_state == "RECOVERED"]
        failed = [r for r in records if r.recovery_state == "FAILED_STOPPED"]
        in_progress = [r for r in records if r.recovery_state in ("INGESTED", "DIAGNOSED", "INTERVENING")]

        recovered_gmv = sum(r.amount for r in recovered)
        recovered_count = len(recovered)

        # Channel cost scoped to the batches the current records belong to.
        #
        # The ledger is append-only, so re-running a batch correctly adds new
        # entries rather than replacing old ones. Summing the whole ledger
        # while GMV stays pinned to the same 50 records made cost climb on
        # every run (24.50 -> 49.00 -> 73.50). Scoping by batch_id keeps spend
        # and revenue measured over the same run.
        active_batches = {r.batch_id for r in records if r.batch_id}
        cost_query = db.query(func.sum(AuditTrailEntry.cost_paise))
        if active_batches:
            cost_query = cost_query.filter(AuditTrailEntry.batch_id.in_(active_batches))
        total_channel_cost_paise = cost_query.scalar() or 0

        recovery_rate = (recovered_count / total_records * 100) if total_records > 0 else 0
        # Integer paise throughout; render to rupees only at the boundary.
        net_roi_paise = recovered_gmv - total_channel_cost_paise
        cost_per_recovery_paise = total_channel_cost_paise // max(recovered_count, 1)

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
                    "channel_cost_paise": 0,
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

        # Lift decomposition. Gross recovery flatters the system; only the
        # difference against the untreated control arm is attributable.
        treated = [r for r in records if r.arm == "treated"]
        control = [r for r in records if r.arm == "control"]
        treated_recovered = [r for r in treated if r.recovery_state == "RECOVERED"]
        control_recovered = [r for r in control if r.recovery_state == "RECOVERED"]

        treated_rate = len(treated_recovered) / len(treated) * 100 if treated else 0.0
        control_rate = len(control_recovered) / len(control) * 100 if control else 0.0

        return {
            "total_records": total_records,
            "total_gmv": total_gmv,
            "recovered_gmv": recovered_gmv,
            "recovery_rate": round(recovery_rate, 1),
            "total_channel_cost_paise": total_channel_cost_paise,
            "total_channel_cost": total_channel_cost_paise / 100.0,
            "net_roi_paise": net_roi_paise,
            "net_roi": net_roi_paise / 100.0,
            "cost_per_recovery_paise": cost_per_recovery_paise,
            "cost_per_recovery": cost_per_recovery_paise / 100.0,
            "recovered_count": recovered_count,
            "failed_count": len(failed),
            "in_progress_count": len(in_progress),
            "class_breakdown": list(class_data.values()),
            "lift": {
                "treated_count": len(treated),
                "control_count": len(control),
                "treated_recovered": len(treated_recovered),
                "control_recovered": len(control_recovered),
                "treated_rate": round(treated_rate, 1),
                "control_rate": round(control_rate, 1),
                "lift_pp": round(treated_rate - control_rate, 1),
                "merchant_margin_percent": MERCHANT_MARGIN_PERCENT,
                # A batch this small cannot carry a causal claim; the demo
                # shows mechanism, results/lift_analysis.md carries the number.
                "sample_warning": (
                    f"n={len(control)} controls - too small for a reliable "
                    f"estimate. See results/lift_analysis.md."
                ) if len(control) < 100 else None,
            },
            "ledger": _ledger_summary(db),
            "records": records_list,
        }
    finally:
        db.close()
