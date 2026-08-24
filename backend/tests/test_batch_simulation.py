import asyncio
import random

import pytest

import app.recovery_simulator as simulator
from app.models import BatchRun, PaymentFailureRecord


@pytest.mark.asyncio
async def test_batch_simulation_processes_all_dataset_records(db_session, monkeypatch):
    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(simulator.asyncio, "sleep", no_sleep)
    random.seed(7)

    result = await simulator.run_batch_simulation(db_session, "batch_test_001")

    batch = db_session.query(BatchRun).filter(BatchRun.batch_id == "batch_test_001").one()
    records = db_session.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.batch_id == "batch_test_001"
    ).all()

    assert result["status"] == "COMPLETED"
    assert result["total_records"] == 50
    assert result["processed_records"] == 50
    assert batch.status == "COMPLETED"
    assert len(records) == 50
    assert all(record.recovery_state != "INGESTED" for record in records)
    assert sum(record.recovery_state == "RECOVERED" for record in records) == result["recovered_count"]
    assert result["total_gmv"] > result["recovered_gmv"] > 0


@pytest.mark.asyncio
async def test_batch_simulation_marks_hard_declines_without_recovery(db_session, monkeypatch):
    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(simulator.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(simulator.random, "random", lambda: 0.0)

    await simulator.run_batch_simulation(db_session, "batch_test_hard_declines")

    hard_declines = db_session.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.batch_id == "batch_test_hard_declines",
        PaymentFailureRecord.failure_class == "HARD_DECLINE",
    ).all()

    assert len(hard_declines) == 4
    assert all(record.recovery_state == "FAILED_STOPPED" for record in hard_declines)
