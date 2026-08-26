"""
RecoverOS Batch Routes
POST /api/batch/run — Trigger batch simulation
GET /api/batch/{batch_id}/status — Live batch metrics

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import uuid
import asyncio

from fastapi import APIRouter, BackgroundTasks

from app.database import SessionLocal
from app.recovery_simulator import run_batch_simulation
from app.models import BatchRun, PaymentFailureRecord
from app.schemas import BatchRunResponse

router = APIRouter()

# Track running simulations
_running_simulations = {}


async def _run_simulation(batch_id: str):
    """Background task to run batch simulation."""
    db = SessionLocal()
    try:
        result = await run_batch_simulation(db, batch_id)
        _running_simulations[batch_id] = result
    except Exception as e:
        print(f"[ERROR] Batch simulation error: {e}")
        _running_simulations[batch_id] = {"error": str(e)}
    finally:
        db.close()


@router.post("/batch/run")
async def run_batch(background_tasks: BackgroundTasks):
    """
    Trigger a 50-record batch simulation.
    Returns batch_id for tracking progress.
    """
    batch_id = f"batch_{uuid.uuid4().hex[:12]}"

    # Start simulation as background task
    background_tasks.add_task(_run_simulation, batch_id)

    return {
        "batch_id": batch_id,
        "status": "STARTED",
        "message": "Batch simulation started. Connect to WebSocket for real-time updates.",
        "ws_url": "ws://localhost:8000/ws/dashboard",
    }


@router.get("/batch/{batch_id}/status")
async def get_batch_status(batch_id: str):
    """
    Get current batch processing status and live metrics.
    """
    db = SessionLocal()
    try:
        batch = db.query(BatchRun).filter(BatchRun.batch_id == batch_id).first()

        if not batch:
            return {"status": "not_found", "batch_id": batch_id}

        # Calculate per-class breakdown
        records = db.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.batch_id == batch_id
        ).all()

        class_breakdown = {}
        for record in records:
            cls = record.failure_class or "UNCLASSIFIED"
            if cls not in class_breakdown:
                class_breakdown[cls] = {
                    "total_count": 0,
                    "recovered_count": 0,
                    "total_gmv": 0,
                    "recovered_gmv": 0,
                }
            class_breakdown[cls]["total_count"] += 1
            class_breakdown[cls]["total_gmv"] += record.amount
            if record.recovery_state == "RECOVERED":
                class_breakdown[cls]["recovered_count"] += 1
                class_breakdown[cls]["recovered_gmv"] += record.amount

        recovery_rate = (batch.recovered_count / batch.total_records * 100) if batch.total_records > 0 else 0

        return {
            "batch_id": batch.batch_id,
            "status": batch.status,
            "total_records": batch.total_records,
            "processed_records": batch.processed_records,
            "recovered_count": batch.recovered_count,
            "total_gmv": batch.total_gmv,
            "recovered_gmv": batch.recovered_gmv,
            "recovery_rate": round(recovery_rate, 1),
            "seed": batch.seed,
            "channel_cost_paise": batch.channel_cost_paise,
            "channel_cost": (batch.channel_cost_paise or 0) / 100.0,
            "net_roi_paise": batch.recovered_gmv - (batch.channel_cost_paise or 0),
            "net_roi": (batch.recovered_gmv - (batch.channel_cost_paise or 0)) / 100.0,
            "cost_per_recovery_paise": (batch.channel_cost_paise or 0) // max(batch.recovered_count, 1),
            "cost_per_recovery": ((batch.channel_cost_paise or 0) // max(batch.recovered_count, 1)) / 100.0,
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
            "class_breakdown": class_breakdown,
        }
    finally:
        db.close()
