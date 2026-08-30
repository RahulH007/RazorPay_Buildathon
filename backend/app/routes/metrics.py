"""
RecoverOS Metrics Routes
GET /api/metrics/dashboard — Aggregated dashboard metrics

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from collections import defaultdict
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query

from app import ai_advisor, ledger
from app.config import MERCHANT_MARGIN_PERCENT
from app.database import SessionLocal
from app.intervention_economics import by_intervention
from app.models import PaymentFailureRecord, AuditTrailEntry, BatchRun
from app.razorpay_client import LIVE_SOURCE
from sqlalchemy import func

router = APIRouter()

# The populations this endpoint can measure.
#
#   batch - one seeded run, the thing "measured money recovered across a batch"
#           actually refers to
#   live  - payments that really failed at Razorpay and were really chased
#   all   - both, for anyone who wants the union stated explicitly
#
# Before this existed the endpoint summed every record ever stored while
# scoping cost to non-null batch ids, so a live recovery's GMV counted as
# revenue and its spend did not count as cost. Revenue and cost came from
# different populations, and the lift block described a third.
SCOPES = ("batch", "live", "all")

# SQLite caps a statement at 999 bound parameters. Cohorts are 65 records
# today, but the cost query binds one parameter per payment id, so it is
# chunked rather than left as a limit nobody would remember.
_ID_CHUNK = 400


def _ledger_summary(db) -> dict:
    """The ledger head, shaped identically for both branches below."""
    head = ledger.get_head(db)
    return {
        "head_hash": head.entry_hash if head else None,
        "entries": (head.sequence_no + 1) if head else 0,
    }


def _resolve_batch_id(db, requested: Optional[str]) -> Optional[str]:
    """
    Which batch `scope=batch` means.

    An explicit id wins, even if it matches nothing - asking for a batch that
    does not exist should report an empty cohort, not silently measure a
    different one. Otherwise the most recent run that still has records, then
    the most recent batch id any record carries.

    None means the database has no batches at all. That is a real state - a
    fresh clone, or a test fixture - and the honest cohort there is the
    unbatched working set rather than nothing.
    """
    if requested:
        return requested

    run = (
        db.query(BatchRun)
        .filter(BatchRun.started_at.isnot(None))
        .order_by(BatchRun.started_at.desc())
        .first()
    )
    if run is not None:
        has_records = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.batch_id == run.batch_id
        ).first()
        if has_records:
            return run.batch_id

    latest = (
        db.query(PaymentFailureRecord.batch_id)
        .filter(PaymentFailureRecord.batch_id.isnot(None))
        .order_by(PaymentFailureRecord.created_at.desc())
        .first()
    )
    return latest[0] if latest else None


def _cohort_records(db, scope: str, batch_id: Optional[str]):
    """The records this reading is about, and the batch id it settled on."""
    if scope == "all":
        return db.query(PaymentFailureRecord).all(), None

    if scope == "live":
        return db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.source == LIVE_SOURCE
        ).all(), None

    resolved = _resolve_batch_id(db, batch_id)
    if resolved is None:
        records = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.batch_id.is_(None),
            PaymentFailureRecord.source != LIVE_SOURCE,
        ).all()
    else:
        records = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.batch_id == resolved
        ).all()
    return records, resolved


def _cohort_cost_paise(db, records) -> int:
    """
    What was spent on exactly these records, and nothing else.

    Grouped by each record's own batch id rather than filtered by one, which is
    what lets a single rule serve all three scopes: a live record's spend is
    found under batch_id IS NULL and is counted, where the old batch-id filter
    dropped it entirely.

    The batch half of the key is still what protects a re-run. The ledger is
    append-only, so re-running a batch adds entries against the same payment
    ids; keying on payment id alone would sum every run ever performed and make
    cost climb on each one.
    """
    by_batch = defaultdict(list)
    for record in records:
        by_batch[record.batch_id].append(record.payment_id)

    total = 0
    for batch_id, payment_ids in by_batch.items():
        for start in range(0, len(payment_ids), _ID_CHUNK):
            chunk = payment_ids[start:start + _ID_CHUNK]
            query = db.query(func.sum(AuditTrailEntry.cost_paise)).filter(
                AuditTrailEntry.payment_id.in_(chunk)
            )
            if batch_id is None:
                query = query.filter(AuditTrailEntry.batch_id.is_(None))
            else:
                query = query.filter(AuditTrailEntry.batch_id == batch_id)
            total += query.scalar() or 0

    return total


def _cohort_meta(scope: str, batch_id: Optional[str], records) -> dict:
    """
    What this reading covers, stated alongside the numbers.

    `arm_coverage` exists because the lift block is computed from `arm`, which
    only the simulator assigns. Live records carry none, so a lift reported
    beside a recovery rate over a wider population was describing a subset
    without saying so. Now it says so.
    """
    with_arm = sum(1 for r in records if r.arm)
    return {
        "scope": scope,
        "batch_id": batch_id,
        "record_count": len(records),
        "sources": sorted({r.source or "synthetic" for r in records}),
        "arm_coverage": {
            "with_arm": with_arm,
            "without_arm": len(records) - with_arm,
        },
    }


def _available_cohorts(db) -> list:
    """Every population this endpoint could be asked for, with its size."""
    cohorts = []

    batched = (
        db.query(
            PaymentFailureRecord.batch_id,
            func.count(PaymentFailureRecord.payment_id),
            func.sum(PaymentFailureRecord.amount),
        )
        .filter(PaymentFailureRecord.batch_id.isnot(None))
        .group_by(PaymentFailureRecord.batch_id)
        .all()
    )
    for batch_id, count, gmv in batched:
        cohorts.append({"scope": "batch", "batch_id": batch_id,
                        "record_count": count, "total_gmv": gmv or 0})

    unbatched_count, unbatched_gmv = (
        db.query(func.count(PaymentFailureRecord.payment_id),
                 func.sum(PaymentFailureRecord.amount))
        .filter(PaymentFailureRecord.batch_id.is_(None),
                PaymentFailureRecord.source != LIVE_SOURCE)
        .one()
    )
    if unbatched_count:
        cohorts.append({"scope": "batch", "batch_id": None,
                        "record_count": unbatched_count,
                        "total_gmv": unbatched_gmv or 0})

    live_count, live_gmv = (
        db.query(func.count(PaymentFailureRecord.payment_id),
                 func.sum(PaymentFailureRecord.amount))
        .filter(PaymentFailureRecord.source == LIVE_SOURCE)
        .one()
    )
    if live_count:
        cohorts.append({"scope": "live", "batch_id": None,
                        "record_count": live_count, "total_gmv": live_gmv or 0})

    total_count, total_gmv = (
        db.query(func.count(PaymentFailureRecord.payment_id),
                 func.sum(PaymentFailureRecord.amount)).one()
    )
    cohorts.append({"scope": "all", "batch_id": None,
                    "record_count": total_count, "total_gmv": total_gmv or 0})

    return cohorts


@router.get("/metrics/dashboard")
async def get_dashboard_metrics(
    # Annotated rather than a Query default, so the real defaults survive a
    # direct call. tests/test_dashboard_metrics.py invokes this function
    # without FastAPI's dependency resolution, and a Query object arriving as
    # `scope` would be neither "batch" nor a valid scope.
    scope: Annotated[str, Query(description="batch | live | all")] = "batch",
    batch_id: Annotated[
        Optional[str], Query(description="Explicit batch to measure")
    ] = None,
):
    """
    Aggregated dashboard metrics:
    Total GMV, Recovered GMV, Recovery Rate, Channel Cost, Net ROI,
    Cost per Recovery, per-class breakdown.
    """
    if scope not in SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown scope {scope!r}; expected one of {', '.join(SCOPES)}",
        )

    db = SessionLocal()
    try:
        # Every figure below is computed over this one population - revenue,
        # cost, ROI, class breakdown and lift alike.
        records, resolved_batch_id = _cohort_records(db, scope, batch_id)
        cohort = _cohort_meta(scope, resolved_batch_id, records)
        cohorts = _available_cohorts(db)

        # Which action recovered how much, at what cost. Over this same
        # cohort - the table would be worse than useless if it described a
        # different population from the totals it sits under.
        economics = by_intervention(db, records)

        # What the model read across this same cohort. Advisory only: the
        # panel exists to show that AI improves the diagnosis, and the field
        # says in its own payload that it authorises nothing.
        ai_insight = ai_advisor.cohort_insight(db, records)

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
                "cohort": cohort,
                "cohorts": cohorts,
                "interventions": economics["interventions"],
                "intervention_summary": economics["summary"],
                "ai_insight": ai_insight,
                "records": [],
            }

        total_records = len(records)
        total_gmv = sum(r.amount for r in records)
        recovered = [r for r in records if r.recovery_state == "RECOVERED"]
        failed = [r for r in records if r.recovery_state == "FAILED_STOPPED"]
        in_progress = [r for r in records if r.recovery_state in ("INGESTED", "DIAGNOSED", "INTERVENING")]

        recovered_gmv = sum(r.amount for r in recovered)
        recovered_count = len(recovered)

        # Channel cost over the cohort's own records - the same records that
        # produced recovered_gmv immediately above, so revenue and cost can no
        # longer describe different populations. Re-run protection is unchanged
        # and now lives in _cohort_cost_paise.
        total_channel_cost_paise = _cohort_cost_paise(db, records)

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
            "cohort": cohort,
            "cohorts": cohorts,
            # Recovery economics per intervention: attempts, wins, spend and
            # net return for each rung of the ladder, strongest first. Derived
            # from the ledger in app/intervention_economics.py - no new column,
            # no parallel tracking table to drift out of step with the chain.
            "interventions": economics["interventions"],
            "intervention_summary": economics["summary"],
            "ai_insight": ai_insight,
            "records": records_list,
        }
    finally:
        db.close()
