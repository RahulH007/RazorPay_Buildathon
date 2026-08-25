"""
RecoverOS Recovery Simulator
Probabilistic batch simulation engine for processing the 50-record dataset.
"""

import json
import uuid
import random
from collections import Counter
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import PaymentFailureRecord, BatchRun
from app.classifier import classify
from app.recovery_actions import execute_recovery
from app.state_machine import transition_state, log_audit
from app.config import (
    RECOVERY_RATES, CHANNEL_COSTS_PAISE, RECOVEROS_SEED, IST,
    HOLDOUT_PERCENT,
)
from app.classifier import RULE_MAP
from app import outcome_engine
from app.policy import ReasonCode
from app.consent import record_opt_out
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


def arrival_time(record_data: dict):
    """
    The moment a record is treated as arriving.

    Records may carry `received_at_ist_hour` so that time-of-day rules such as
    quiet hours are demonstrable in a batch that actually runs at midday.
    Returns None for records with no stated arrival, meaning "now".
    """
    hour = record_data.get("received_at_ist_hour")
    if hour is None:
        return None
    return datetime.now(IST).replace(hour=int(hour), minute=0, second=0, microsecond=0)


async def run_batch_simulation(db: Session, batch_id: str) -> dict:
    """
    Run the full 50-record batch simulation.
    Processes each record: classify → check guards → execute action → determine outcome.
    Emits WebSocket events for real-time dashboard updates.
    """
    # Load dataset
    dataset = load_dataset()

    # Seed per run so a reported number can always be reproduced. Uses a
    # local Random instance rather than the global module state, so a
    # concurrent caller cannot perturb this run's draw sequence.
    rng = random.Random(RECOVEROS_SEED)

    # Assign the control group before processing anything. Holdout is decided
    # per contact and stratified by failure class, so it must be computed over
    # the whole population rather than record by record.
    for item in dataset:
        item["_failure_class"] = RULE_MAP[item["error"]["reason"]].value
    held_out = outcome_engine.assign_holdout(dataset, RECOVEROS_SEED, HOLDOUT_PERCENT)

    # Create batch run record
    batch = db.query(BatchRun).filter(BatchRun.batch_id == batch_id).first()
    if not batch:
        batch = BatchRun(
            batch_id=batch_id,
            status="RUNNING",
            seed=RECOVEROS_SEED,
            total_records=len(dataset),
            started_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.commit()
    else:
        batch.status = "RUNNING"
        batch.seed = RECOVEROS_SEED
        batch.total_records = len(dataset)
        batch.processed_records = 0
        batch.recovered_count = 0
        batch.total_gmv = 0
        batch.recovered_gmv = 0
        batch.channel_cost_paise = 0
        batch.started_at = datetime.now(timezone.utc)
        batch.completed_at = None
        db.commit()

    total_gmv = 0
    recovered_gmv = 0
    recovered_count = 0
    total_channel_cost_paise = 0
    processed = 0
    # Why we stopped, per record. Surfaced in the batch result so restraint
    # is reported alongside recovery rather than hidden.
    reason_codes = Counter()
    treated_count = 0
    control_count = 0
    control_recovered = 0
    control_gmv = 0
    attributable_count = 0
    attributable_gmv = 0

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

        # A contact who withdrew consent on an earlier payment. Seeded at
        # ingestion because the registry is meant to outlive any single
        # payment - that persistence is the property being demonstrated.
        prior_consent = record_data.get("consent") or {}
        if prior_consent.get("opted_out"):
            record_opt_out(
                db,
                phone=record.customer_phone,
                source=prior_consent.get("source", "api"),
                payment_id=record.payment_id,
                channel="all",
                batch_id=batch_id,
            )

        # 2. Classify the record
        failure_class = await classify(db, record)

        if record.recovery_state == "FAILED_STOPPED":
            # Classified straight to terminal (hard decline). Record why.
            await execute_recovery(db, record)
            reason_codes["HARD_DECLINE"] += 1
            processed += 1
            batch.processed_records = processed
            batch.total_gmv = total_gmv
            db.commit()
            continue

        # 3. Walk the escalation ladder.
        #
        # The policy engine is re-consulted before every attempt rather than
        # once per record. That is what makes the attempt cap reachable and
        # the cost ceiling binding: both are evaluated against spend that has
        # actually accumulated, not against zero.
        behaviour = outcome_engine.Behaviour.from_record(record_data)
        is_holdout = outcome_engine.is_held_out(record.customer_phone, held_out)
        now = arrival_time(record_data)
        attributable = False
        record.arm = "control" if is_holdout else "treated"
        db.commit()

        while record.recovery_state not in ("RECOVERED", "FAILED_STOPPED"):
            result = await execute_recovery(db, record, now=now, is_holdout=is_holdout)

            if result.get("action") in ("declined", "no_action"):
                reason_codes[result.get("reason_code", "UNKNOWN")] += 1

                # A holdout is not a failure - it is an untreated observation,
                # and whether it recovers on its own is the whole measurement.
                if result.get("reason_code") == ReasonCode.HOLDOUT_CONTROL:
                    control = outcome_engine.control_outcome(behaviour)
                    log_audit(
                        db, record,
                        action="CONTROL_OBSERVED",
                        actor="outcome_engine",
                        details=control.reason,
                    )
                    if control.recovered:
                        await transition_state(
                            db, record,
                            to_state="RECOVERED",
                            actor="outcome_engine",
                            details=control.reason,
                        )
                    else:
                        await transition_state(
                            db, record,
                            to_state="FAILED_STOPPED",
                            actor="outcome_engine",
                            details=control.reason,
                        )
                break

            total_channel_cost_paise += result.get("decision", {}).get("cost_paise", 0)
            decision = result.get("decision", {})
            channel = decision.get("channel")
            attempt_no = decision.get("attempt_number", 0)

            outcome = outcome_engine.attempt_outcome(
                record.payment_id, behaviour, channel, attempt_no, RECOVEROS_SEED
            )

            if outcome.recovered:
                attributable = outcome.attributable
                await transition_state(
                    db, record,
                    to_state="RECOVERED",
                    actor="outcome_engine",
                    details=outcome.reason,
                )
            elif result.get("action") == "human_queue":
                await transition_state(
                    db, record,
                    to_state="FAILED_STOPPED",
                    actor="system",
                    details="Handed to the accounts team; automated recovery ends here.",
                )
                reason_codes["ESCALATED_TO_HUMAN"] += 1
                break

        if record.recovery_state == "RECOVERED":
            recovered_gmv += record.amount
            recovered_count += 1
            if is_holdout:
                control_recovered += 1
                control_gmv += record.amount
            elif attributable:
                attributable_count += 1
                attributable_gmv += record.amount

        if is_holdout:
            control_count += 1
        else:
            treated_count += 1

        # Update batch progress
        processed += 1
        batch.processed_records = processed
        batch.total_gmv = total_gmv
        batch.recovered_gmv = recovered_gmv
        batch.recovered_count = recovered_count
        batch.channel_cost_paise = total_channel_cost_paise
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
                "channel_cost_paise": total_channel_cost_paise,
                "net_roi_paise": recovered_gmv - total_channel_cost_paise,
            })
        except Exception:
            pass

        # Stagger processing for streaming effect (100-300ms)
        await asyncio.sleep(rng.uniform(0.1, 0.3))

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
        "seed": RECOVEROS_SEED,
        "reason_codes": dict(reason_codes),
        "treated_count": treated_count,
        "control_count": control_count,
        "control_recovered": control_recovered,
        "control_gmv": control_gmv,
        "attributable_count": attributable_count,
        "attributable_gmv": attributable_gmv,
        "channel_cost_paise": total_channel_cost_paise,
        "net_roi_paise": recovered_gmv - total_channel_cost_paise,
        "cost_per_recovery_paise": total_channel_cost_paise // max(recovered_count, 1),
    }
