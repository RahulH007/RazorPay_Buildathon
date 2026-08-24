"""
RecoverOS Recovery Simulator
Probabilistic batch simulation engine for processing the 50-record dataset.
"""

import json
import uuid
import random
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import PaymentFailureRecord, BatchRun
from app.classifier import classify
from app.recovery_actions import execute_recovery
from app.state_machine import transition_state, log_audit
from app.config import RECOVERY_RATES, CHANNEL_COSTS
from app.websocket_manager import manager


# Path to the synthetic dataset
DATASET_PATH = Path(__file__).parent.parent / "data" / "test_batch_50.json"


def load_dataset() -> list:
    """Load the 50-record synthetic dataset."""
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def ingest_record(db: Session, record_data: dict, batch_id: str) -> PaymentFailureRecord:
    """Ingest a single record from the dataset into the database."""
    customer = record_data.get("customer", {})
    error = record_data.get("error", {})

    # Check if record already exists (from a previous batch run)
    existing = db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.payment_id == record_data["payment_id"]
    ).first()

    if existing:
        # Reset state for re-simulation
        existing.recovery_state = "INGESTED"
        existing.failure_class = None
        existing.recovery_channel = None
        existing.batch_id = batch_id
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        return existing

    record = PaymentFailureRecord(
        payment_id=record_data["payment_id"],
        amount=record_data["amount"],
        currency=record_data.get("currency", "INR"),
        method=record_data["method"],
        subscription_id=record_data.get("subscription_id"),
        invoice_id=record_data.get("invoice_id"),
        merchant_id=record_data.get("merchant_id", "merchant_A1b2C3"),
        customer_name=customer.get("name", "Unknown"),
        customer_email=customer.get("email"),
        customer_phone=customer.get("phone", "+919999999999"),
        error_source=error.get("source"),
        error_step=error.get("step"),
        error_reason=error.get("reason", "unknown"),
        error_description=error.get("description"),
        recovery_state="INGESTED",
        batch_id=batch_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


async def run_batch_simulation(db: Session, batch_id: str) -> dict:
    """
    Run the full 50-record batch simulation.
    Processes each record: classify → check guards → execute action → determine outcome.
    Emits WebSocket events for real-time dashboard updates.
    """
    # Load dataset
    dataset = load_dataset()

    # Create batch run record
    batch = db.query(BatchRun).filter(BatchRun.batch_id == batch_id).first()
    if not batch:
        batch = BatchRun(
            batch_id=batch_id,
            status="RUNNING",
            total_records=len(dataset),
            started_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.commit()
    else:
        batch.status = "RUNNING"
        batch.total_records = len(dataset)
        batch.processed_records = 0
        batch.recovered_count = 0
        batch.total_gmv = 0
        batch.recovered_gmv = 0
        batch.channel_cost = 0.0
        batch.started_at = datetime.now(timezone.utc)
        batch.completed_at = None
        db.commit()

    total_gmv = 0
    recovered_gmv = 0
    recovered_count = 0
    total_channel_cost = 0.0
    processed = 0

    for record_data in dataset:
        # 1. Ingest record
        record = ingest_record(db, record_data, batch_id)
        total_gmv += record.amount

        # Broadcast ingestion event
        try:
            await manager.send_batch_progress(batch_id, processed, len(dataset), {
                "payment_id": record.payment_id,
                "amount": record.amount,
                "customer_name": record.customer_name,
                "method": record.method,
                "error_reason": record.error_reason,
            })
        except Exception:
            pass

        # Log ingestion
        log_audit(
            db, record,
            action="RECORD_INGESTED",
            actor="system",
            details=f"Batch {batch_id}: Record ingested — ₹{record.amount / 100:,.2f} via {record.method}",
        )

        # 2. Classify the record
        failure_class = await classify(db, record)

        # 3. Execute recovery (if not already at terminal state)
        if record.recovery_state not in ("RECOVERED", "FAILED_STOPPED"):
            await execute_recovery(db, record)

        # 4. Determine probabilistic outcome
        base_rate = RECOVERY_RATES.get(failure_class.value, 0.0)
        channel_cost = CHANNEL_COSTS.get(failure_class.value, 0.0)
        total_channel_cost += channel_cost

        if record.recovery_state == "INTERVENING":
            # Probabilistic recovery outcome
            recovered = random.random() < base_rate
            if recovered:
                await transition_state(
                    db, record,
                    to_state="RECOVERED",
                    actor="system",
                    details=f"Payment captured (simulated). Recovery rate: {base_rate * 100:.0f}%",
                )
                recovered_gmv += record.amount
                recovered_count += 1
            else:
                await transition_state(
                    db, record,
                    to_state="FAILED_STOPPED",
                    actor="system",
                    details=f"Recovery attempt unsuccessful (simulated). Base rate: {base_rate * 100:.0f}%",
                )
        elif record.recovery_state == "RECOVERED":
            recovered_gmv += record.amount
            recovered_count += 1

        # Update batch progress
        processed += 1
        batch.processed_records = processed
        batch.total_gmv = total_gmv
        batch.recovered_gmv = recovered_gmv
        batch.recovered_count = recovered_count
        batch.channel_cost = total_channel_cost
        db.commit()

        # Broadcast progress
        try:
            recovery_rate = (recovered_count / processed * 100) if processed > 0 else 0
            await manager.send_metric_update({
                "batch_id": batch_id,
                "processed": processed,
                "total": len(dataset),
                "total_gmv": total_gmv,
                "recovered_gmv": recovered_gmv,
                "recovered_count": recovered_count,
                "recovery_rate": round(recovery_rate, 1),
                "channel_cost": round(total_channel_cost, 2),
                "net_roi": round((recovered_gmv / 100) - total_channel_cost, 2),
            })
        except Exception:
            pass

        # Stagger processing for streaming effect (100-300ms)
        await asyncio.sleep(random.uniform(0.1, 0.3))

    # Finalize batch
    batch.status = "COMPLETED"
    batch.completed_at = datetime.now(timezone.utc)
    db.commit()

    recovery_rate = (recovered_count / len(dataset) * 100) if dataset else 0

    return {
        "batch_id": batch_id,
        "status": "COMPLETED",
        "total_records": len(dataset),
        "processed_records": processed,
        "recovered_count": recovered_count,
        "total_gmv": total_gmv,
        "recovered_gmv": recovered_gmv,
        "recovery_rate": round(recovery_rate, 1),
        "channel_cost": round(total_channel_cost, 2),
        "net_roi": round((recovered_gmv / 100) - total_channel_cost, 2),
        "cost_per_recovery": round(total_channel_cost / max(recovered_count, 1), 2),
    }
