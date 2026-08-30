"""
Cohort-scoped dashboard metrics: one population per reading.

The judged sentence is "show measured money recovered across a batch". The
endpoint used to answer a different question: it summed every record the
database had ever held, of any provenance, while scoping cost to non-null
batch ids. Live webhook records carry no batch id, so their GMV counted as
revenue and their spend did not count as cost, and the lift block - keyed on
`arm`, which only the simulator assigns - described a third population again.
Three denominators, printed as one number, erring in the flattering direction.

Nothing in tests/test_dashboard_metrics.py could catch that: every record in
its fixture is synthetic and unbatched, so the three populations coincide. The
defect only appears when a batch and live traffic exist together, which is
exactly the state of any database that has actually taken a webhook. That
mixture is what this file builds.

The invariant under test is one line long: every figure in a reading -
revenue, recovery rate, cost, ROI and lift alike - is computed over the same
records, and the reading says which records those are.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import ledger
from app.database import Base
from app.models import AuditTrailEntry, PaymentFailureRecord
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.routes import metrics as metrics_route

BATCH = "batch_cohort_test"
OTHER_BATCH = "batch_cohort_previous_run"

SYNTH_AMOUNT = 100_000      # Rs 1,000
LIVE_AMOUNT = 45_000        # Rs 450, the amount the real Test Mode runs used
ATTEMPT_COST = 50           # one WhatsApp send

# Deliberately different recovery rates per cohort, so a reading that silently
# mixed them could not coincidentally produce the right number.
SYNTH_TOTAL, SYNTH_RECOVERED = 4, 2      # 50.0%
LIVE_TOTAL, LIVE_RECOVERED = 3, 1        # 33.3%


@pytest.fixture
def dashboard(db_session, monkeypatch):
    """The real function, bound to the test session."""
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(metrics_route, "SessionLocal", lambda: db_session)

    async def read(**kwargs):
        return await metrics_route.get_dashboard_metrics(**kwargs)

    return read


def _add(db, payment_record, payment_id, amount, state, source, batch_id, arm):
    record = payment_record(
        payment_id=payment_id,
        amount=amount,
        failure_class="AUTH_FRICTION",
        recovery_state=state,
        recovery_channel="whatsapp_link",
        error_reason="authentication_failed",
        source=source,
        batch_id=batch_id,
        arm=arm,
    )
    db.add(record)
    db.commit()
    # One attempt each, stamped into the same batch context the record carries.
    ledger.append_entry(
        db, payment_id=payment_id, batch_id=batch_id,
        action="WHATSAPP_LINK_SENT", actor="system",
        details="cohort fixture", cost_paise=ATTEMPT_COST,
    )
    return record


@pytest.fixture
def mixed(db_session, payment_record):
    """
    A batch and live traffic in one database - the state of any deployment
    that has taken a webhook.
    """
    for i in range(SYNTH_TOTAL):
        _add(
            db_session, payment_record,
            payment_id=f"pay_synth_{i}", amount=SYNTH_AMOUNT,
            state="RECOVERED" if i < SYNTH_RECOVERED else "INTERVENING",
            source=SYNTHETIC_SOURCE, batch_id=BATCH,
            arm="control" if i == SYNTH_TOTAL - 1 else "treated",
        )

    for i in range(LIVE_TOTAL):
        _add(
            db_session, payment_record,
            payment_id=f"pay_live_{i}", amount=LIVE_AMOUNT,
            state="RECOVERED" if i < LIVE_RECOVERED else "INTERVENING",
            source=LIVE_SOURCE, batch_id=None, arm=None,
        )

    return db_session


SYNTH_COST = SYNTH_TOTAL * ATTEMPT_COST      # 200p
LIVE_COST = LIVE_TOTAL * ATTEMPT_COST        # 150p


# --- Each scope measures its own population ---------------------------------


@pytest.mark.asyncio
async def test_batch_scope_reports_only_the_batch(mixed, dashboard):
    result = await dashboard(scope="batch")

    assert result["total_records"] == SYNTH_TOTAL
    assert result["total_gmv"] == SYNTH_TOTAL * SYNTH_AMOUNT
    assert result["recovered_count"] == SYNTH_RECOVERED
    assert result["recovered_gmv"] == SYNTH_RECOVERED * SYNTH_AMOUNT
    assert result["recovery_rate"] == 50.0
    assert result["total_channel_cost_paise"] == SYNTH_COST
    assert result["cohort"]["batch_id"] == BATCH
    assert result["cohort"]["sources"] == [SYNTHETIC_SOURCE]


@pytest.mark.asyncio
async def test_live_scope_reports_live_records_and_counts_their_spend(mixed, dashboard):
    """
    The defect, stated directly. Live spend was dropped from cost by the old
    batch-id filter while live GMV was counted as revenue.
    """
    result = await dashboard(scope="live")

    assert result["total_records"] == LIVE_TOTAL
    assert result["total_gmv"] == LIVE_TOTAL * LIVE_AMOUNT
    assert result["recovered_count"] == LIVE_RECOVERED
    assert result["recovery_rate"] == 33.3
    assert result["total_channel_cost_paise"] == LIVE_COST
    assert result["cohort"]["sources"] == [LIVE_SOURCE]


@pytest.mark.asyncio
async def test_all_scope_counts_every_record_and_every_rupee(mixed, dashboard):
    result = await dashboard(scope="all")

    assert result["total_records"] == SYNTH_TOTAL + LIVE_TOTAL
    assert result["total_gmv"] == SYNTH_TOTAL * SYNTH_AMOUNT + LIVE_TOTAL * LIVE_AMOUNT
    assert result["recovered_count"] == SYNTH_RECOVERED + LIVE_RECOVERED
    # The whole point: the union's cost is the sum of the parts, not the
    # batch's cost with live spend quietly missing.
    assert result["total_channel_cost_paise"] == SYNTH_COST + LIVE_COST
    assert sorted(result["cohort"]["sources"]) == [LIVE_SOURCE, SYNTHETIC_SOURCE]


@pytest.mark.asyncio
async def test_the_scopes_partition_the_database(mixed, dashboard):
    """batch + live == all, in records, GMV and spend alike."""
    batch = await dashboard(scope="batch")
    live = await dashboard(scope="live")
    everything = await dashboard(scope="all")

    assert batch["total_records"] + live["total_records"] == everything["total_records"]
    assert batch["total_gmv"] + live["total_gmv"] == everything["total_gmv"]
    assert (batch["total_channel_cost_paise"] + live["total_channel_cost_paise"]
            == everything["total_channel_cost_paise"])
    assert (batch["recovered_gmv"] + live["recovered_gmv"]
            == everything["recovered_gmv"])


# --- Revenue and cost come from the same records ----------------------------


@pytest.mark.parametrize("scope", ["batch", "live", "all"])
@pytest.mark.asyncio
async def test_cost_covers_exactly_the_records_being_reported(mixed, dashboard, scope):
    """
    The invariant the old endpoint broke: every record contributing to GMV has
    its own spend inside the reported cost, and no record outside the cohort
    contributes any.
    """
    result = await dashboard(scope=scope)
    reported_ids = {r["payment_id"] for r in result["records"]}

    expected = 0
    for entry in mixed.query(AuditTrailEntry).all():
        if entry.payment_id in reported_ids:
            record = mixed.query(PaymentFailureRecord).filter(
                PaymentFailureRecord.payment_id == entry.payment_id).one()
            if entry.batch_id == record.batch_id:
                expected += entry.cost_paise or 0

    assert result["total_channel_cost_paise"] == expected
    assert len(reported_ids) == result["total_records"]


@pytest.mark.parametrize("scope", ["batch", "live", "all"])
@pytest.mark.asyncio
async def test_roi_is_internally_consistent(mixed, dashboard, scope):
    result = await dashboard(scope=scope)

    assert result["net_roi_paise"] == (
        result["recovered_gmv"] - result["total_channel_cost_paise"]
    )
    assert result["total_channel_cost"] == result["total_channel_cost_paise"] / 100.0


@pytest.mark.parametrize("scope", ["batch", "live", "all"])
@pytest.mark.asyncio
async def test_the_class_breakdown_sums_to_the_cohort(mixed, dashboard, scope):
    result = await dashboard(scope=scope)

    assert sum(c["total_count"] for c in result["class_breakdown"]) == result["total_records"]
    assert sum(c["total_gmv"] for c in result["class_breakdown"]) == result["total_gmv"]
    assert sum(c["recovered_count"] for c in result["class_breakdown"]) == result["recovered_count"]


# --- Lift describes the cohort, and says how much of it it covers -----------


@pytest.mark.asyncio
async def test_lift_covers_the_whole_batch_cohort(mixed, dashboard):
    result = await dashboard(scope="batch")
    lift = result["lift"]

    assert lift["treated_count"] + lift["control_count"] == result["total_records"]
    assert result["cohort"]["arm_coverage"] == {
        "with_arm": SYNTH_TOTAL, "without_arm": 0,
    }


@pytest.mark.asyncio
async def test_arm_coverage_declares_the_shortfall_when_live_is_included(
    mixed, dashboard
):
    """
    Live records carry no arm, so a lift reported beside an all-scope recovery
    rate covers only part of the population. It must say so rather than let the
    two be read as one.
    """
    result = await dashboard(scope="all")
    lift = result["lift"]

    assert result["cohort"]["arm_coverage"] == {
        "with_arm": SYNTH_TOTAL, "without_arm": LIVE_TOTAL,
    }
    assert lift["treated_count"] + lift["control_count"] < result["total_records"]


@pytest.mark.asyncio
async def test_live_scope_reports_no_arms_at_all(mixed, dashboard):
    result = await dashboard(scope="live")

    assert result["cohort"]["arm_coverage"] == {
        "with_arm": 0, "without_arm": LIVE_TOTAL,
    }
    assert result["lift"]["treated_count"] == 0
    assert result["lift"]["control_count"] == 0


# --- Re-run protection ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_previous_runs_entries_do_not_inflate_cost(mixed, dashboard):
    """
    The reason the original batch-id filter existed, preserved.

    The ledger is append-only, so re-running a batch adds entries against the
    same payment ids rather than replacing them. Keying cost on payment id
    alone would sum every run ever performed; the batch half of the key is what
    stops it.
    """
    for i in range(SYNTH_TOTAL):
        ledger.append_entry(
            mixed, payment_id=f"pay_synth_{i}", batch_id=OTHER_BATCH,
            action="WHATSAPP_LINK_SENT", actor="system",
            details="stale entry from an earlier run", cost_paise=ATTEMPT_COST,
        )

    result = await dashboard(scope="batch")

    assert result["total_channel_cost_paise"] == SYNTH_COST


# --- Cohort metadata --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_reading_names_the_population_it_describes(mixed, dashboard):
    batch = await dashboard(scope="batch")

    assert batch["cohort"]["scope"] == "batch"
    assert batch["cohort"]["batch_id"] == BATCH
    assert batch["cohort"]["record_count"] == SYNTH_TOTAL


@pytest.mark.asyncio
async def test_available_cohorts_are_listed_with_their_sizes(mixed, dashboard):
    cohorts = (await dashboard(scope="batch"))["cohorts"]
    by_key = {(c["scope"], c["batch_id"]): c for c in cohorts}

    assert by_key[("batch", BATCH)]["record_count"] == SYNTH_TOTAL
    assert by_key[("live", None)]["record_count"] == LIVE_TOTAL
    assert by_key[("all", None)]["record_count"] == SYNTH_TOTAL + LIVE_TOTAL
    assert by_key[("all", None)]["total_gmv"] == (
        SYNTH_TOTAL * SYNTH_AMOUNT + LIVE_TOTAL * LIVE_AMOUNT
    )


@pytest.mark.asyncio
async def test_the_cohorts_listing_is_the_same_whatever_scope_is_read(mixed, dashboard):
    batch = (await dashboard(scope="batch"))["cohorts"]
    live = (await dashboard(scope="live"))["cohorts"]

    assert batch == live


# --- Defaults, selection and bad input --------------------------------------


@pytest.mark.asyncio
async def test_the_default_scope_is_the_batch(mixed, dashboard):
    assert (await dashboard())["cohort"]["scope"] == "batch"
    assert (await dashboard())["total_records"] == SYNTH_TOTAL


@pytest.mark.asyncio
async def test_an_explicit_batch_id_selects_that_batch(mixed, dashboard):
    result = await dashboard(scope="batch", batch_id=BATCH)

    assert result["cohort"]["batch_id"] == BATCH
    assert result["total_records"] == SYNTH_TOTAL


@pytest.mark.asyncio
async def test_an_unknown_batch_id_is_an_empty_cohort_not_an_error(mixed, dashboard):
    """
    Asking for a batch that does not exist must report nothing, never silently
    measure a different one.
    """
    result = await dashboard(scope="batch", batch_id="batch_does_not_exist")

    assert result["cohort"]["batch_id"] == "batch_does_not_exist"
    assert result["cohort"]["record_count"] == 0
    assert result["total_records"] == 0
    assert result["total_gmv"] == 0
    assert result["total_channel_cost_paise"] == 0
    assert result["records"] == []


@pytest.mark.asyncio
async def test_an_unknown_scope_is_rejected(mixed, dashboard):
    with pytest.raises(HTTPException) as excinfo:
        await dashboard(scope="everything")

    assert excinfo.value.status_code == 400
    assert "unknown scope" in excinfo.value.detail


@pytest.mark.parametrize("scope", ["batch", "live", "all"])
@pytest.mark.asyncio
async def test_an_empty_database_returns_the_zero_shape_for_every_scope(
    db_session, dashboard, scope
):
    result = await dashboard(scope=scope)

    assert result["total_records"] == 0
    assert result["total_gmv"] == 0
    assert result["total_channel_cost_paise"] == 0
    assert result["net_roi_paise"] == 0
    assert result["records"] == []
    assert result["cohort"]["scope"] == scope
    assert result["cohort"]["record_count"] == 0


@pytest.mark.parametrize("scope", ["batch", "live", "all"])
@pytest.mark.asyncio
async def test_both_branches_carry_the_cohort_keys(mixed, dashboard, monkeypatch, scope):
    """
    The empty and populated branches are still hand-written duplicates, which
    is what produced a 500 once before. Both must carry the new keys.

    The empty reading comes from a second database rather than from deleting
    the fixture's records: these records have ledger entries against them, and
    the append-only guard correctly refuses the cascade that a delete would
    provoke.
    """
    populated = await dashboard(scope=scope)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    blank = sessionmaker(bind=engine)()
    monkeypatch.setattr(metrics_route, "SessionLocal", lambda: blank)

    empty = await metrics_route.get_dashboard_metrics(scope=scope)

    assert empty["total_records"] == 0
    assert set(empty) == set(populated)
    assert set(empty["cohort"]) == set(populated["cohort"])
    assert set(empty["lift"]) == set(populated["lift"])
