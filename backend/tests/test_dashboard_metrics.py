"""
Priority 11: the dashboard's own numbers, read from the dashboard.

`get_dashboard_metrics` is what the UI renders and what a judge reads. Until
now nothing in the suite called it - the two "exactly once" tests re-implement
the aggregation with their own queries, and one imports the function only to
mark it unused. That is how a 500 lived in it: the `if not records:` branch
built its `lift` dict from locals defined 110 lines further down, so every
zero-record database answered UnboundLocalError.

    RAISED: UnboundLocalError cannot access local variable 'treated'

A fresh clone, or `make clean` followed by opening the dashboard, hit it every
time. This file covers the three states the endpoint is actually asked about -
empty, seeded, recovered - and pins the shape so the two branches cannot drift
apart again.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest

from app import ledger, settlement
from app.config import MERCHANT_MARGIN_PERCENT
from app.models import AuditTrailEntry, PaymentFailureRecord
from app.routes import metrics as metrics_route

from test_link_correlation_isolation import (  # noqa: F401 - `many` is a fixture
    A, B, C, D, AMOUNT, ODD_AMOUNT, PLINK_B, PLINK_C, many, payload, state,
)

TOP_LEVEL_KEYS = {
    "total_records", "total_gmv", "recovered_gmv", "recovery_rate",
    "total_channel_cost_paise", "total_channel_cost", "net_roi_paise", "net_roi",
    "cost_per_recovery_paise", "cost_per_recovery", "recovered_count",
    "failed_count", "in_progress_count", "class_breakdown", "lift", "ledger",
    # Which population every figure above describes, and which others exist.
    # Added when the endpoint became cohort-scoped; both branches carry them,
    # which is what the shape test below exists to keep true.
    "cohort", "cohorts",
    # Which action recovered how much, at what cost. Added when the economics
    # became attributable per intervention; both branches carry them.
    "interventions", "intervention_summary",
    # What the model read across the cohort. Advisory only, and the payload
    # says so itself.
    "ai_insight",
    "records",
}

LIFT_KEYS = {
    "treated_count", "control_count", "treated_recovered", "control_recovered",
    "treated_rate", "control_rate", "lift_pp", "merchant_margin_percent",
    "sample_warning",
}


@pytest.fixture
def dashboard(db_session, monkeypatch):
    """The real function, bound to the test session."""
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(metrics_route, "SessionLocal", lambda: db_session)

    async def read():
        return await metrics_route.get_dashboard_metrics()

    return read


# --- Empty ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_empty_database_returns_zero_metrics_not_an_error(db_session, dashboard):
    """The regression. This raised UnboundLocalError before the fix."""
    assert db_session.query(PaymentFailureRecord).count() == 0

    result = await dashboard()

    assert result["total_records"] == 0
    assert result["total_gmv"] == 0
    assert result["recovered_count"] == 0
    assert result["recovered_gmv"] == 0
    assert result["recovery_rate"] == 0.0
    assert result["failed_count"] == 0
    assert result["in_progress_count"] == 0
    assert result["total_channel_cost_paise"] == 0
    assert result["net_roi_paise"] == 0
    assert result["cost_per_recovery_paise"] == 0
    assert result["class_breakdown"] == []
    assert result["records"] == []


@pytest.mark.asyncio
async def test_the_empty_lift_block_is_well_formed(db_session, dashboard):
    lift = (await dashboard())["lift"]

    assert set(lift) == LIFT_KEYS
    assert lift["treated_count"] == lift["control_count"] == 0
    assert lift["treated_recovered"] == lift["control_recovered"] == 0
    assert lift["treated_rate"] == lift["control_rate"] == lift["lift_pp"] == 0.0
    assert lift["merchant_margin_percent"] == MERCHANT_MARGIN_PERCENT
    # A zero-control batch carries no causal claim, and says so.
    assert "n=0 controls" in lift["sample_warning"]


@pytest.mark.asyncio
async def test_the_two_branches_return_the_same_shape(db_session, dashboard, many):
    """
    The 500 existed because the empty branch was a hand-copied duplicate that
    drifted. Pinning both key sets is what stops that recurring.
    """
    populated = await dashboard()

    for record in db_session.query(PaymentFailureRecord).all():
        db_session.delete(record)
    db_session.commit()
    empty = await dashboard()

    assert set(empty) == set(populated) == TOP_LEVEL_KEYS
    assert set(empty["lift"]) == set(populated["lift"]) == LIFT_KEYS
    assert set(empty["ledger"]) == set(populated["ledger"]) == {"head_hash", "entries"}


@pytest.mark.asyncio
async def test_an_empty_record_table_still_reports_the_real_ledger(db_session, dashboard):
    """
    The ledger is append-only, so "no records" does not imply "no entries".
    Reporting zero here would disagree with verify_chain on exactly the database
    where someone is most likely to be checking.
    """
    ledger.append_entry(
        db_session, payment_id="pay_GONE_000001", batch_id=None,
        action="RECORD_INGESTED", actor="system", details="record later removed",
    )
    db_session.commit()

    result = await dashboard()
    chain = ledger.verify_chain(db_session)

    assert result["total_records"] == 0
    assert result["ledger"]["entries"] == chain.entries_checked == 1
    assert result["ledger"]["head_hash"] == ledger.get_head(db_session).entry_hash
    assert chain.valid is True


# --- Seeded, nothing recovered yet -----------------------------------------


@pytest.mark.asyncio
async def test_a_seeded_database_reports_no_recoveries(db_session, dashboard, many):
    result = await dashboard()

    assert result["total_records"] == 4
    assert result["total_gmv"] == AMOUNT * 3 + ODD_AMOUNT
    assert result["recovered_count"] == 0
    assert result["recovered_gmv"] == 0
    assert result["recovery_rate"] == 0.0
    assert result["in_progress_count"] == 4
    assert result["failed_count"] == 0
    assert len(result["records"]) == 4

    breakdown = {c["failure_class"]: c for c in result["class_breakdown"]}
    assert breakdown["AUTH_FRICTION"]["total_count"] == 4
    assert breakdown["AUTH_FRICTION"]["recovered_count"] == 0


# --- Recovered --------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovered_count_and_gmv_follow_the_recoveries(
        db_session, dashboard, many):
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    one = await dashboard()

    assert one["recovered_count"] == 1
    assert one["recovered_gmv"] == AMOUNT
    assert one["recovery_rate"] == 25.0        # 1 of 4
    assert one["in_progress_count"] == 3

    await settlement.handle_payment_link_paid(
        db_session, payload(PLINK_C, payment_id="pay_NEW_C0001"))
    two = await dashboard()

    assert two["recovered_count"] == 2
    assert two["recovered_gmv"] == AMOUNT * 2
    assert two["recovery_rate"] == 50.0
    assert two["in_progress_count"] == 2

    breakdown = {c["failure_class"]: c for c in two["class_breakdown"]}
    assert breakdown["AUTH_FRICTION"]["recovered_count"] == 2
    assert breakdown["AUTH_FRICTION"]["recovered_gmv"] == AMOUNT * 2


@pytest.mark.asyncio
async def test_the_dashboard_agrees_with_the_database(db_session, dashboard, many):
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    await settlement.handle_payment_link_paid(
        db_session, payload(PLINK_C, payment_id="pay_NEW_C0001"))

    result = await dashboard()
    rows = db_session.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.recovery_state == "RECOVERED").all()

    assert result["recovered_count"] == len(rows)
    assert result["recovered_gmv"] == sum(r.amount for r in rows)
    assert result["total_records"] == db_session.query(PaymentFailureRecord).count()
    assert result["total_gmv"] == sum(
        r.amount for r in db_session.query(PaymentFailureRecord).all())


# --- Ledger consistency across all three states -----------------------------


@pytest.mark.asyncio
async def test_the_reported_ledger_matches_verify_chain_in_every_state(
        db_session, dashboard, many):
    async def agrees():
        result = await dashboard()
        chain = ledger.verify_chain(db_session)
        head = ledger.get_head(db_session)
        assert chain.valid is True, chain.reason
        assert result["ledger"]["entries"] == chain.entries_checked
        assert result["ledger"]["entries"] == db_session.query(AuditTrailEntry).count()
        assert result["ledger"]["head_hash"] == (head.entry_hash if head else None)
        return result

    seeded = await agrees()
    assert seeded["ledger"]["entries"] == 0        # the fixture writes no entries

    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    recovered = await agrees()
    assert recovered["ledger"]["entries"] > 0

    # A refusal is on the chain too.
    await settlement.handle_payment_link_paid(
        db_session, payload(PLINK_C, amount=ODD_AMOUNT))
    held = await agrees()
    assert held["ledger"]["entries"] > recovered["ledger"]["entries"]
    assert held["recovered_count"] == 1
