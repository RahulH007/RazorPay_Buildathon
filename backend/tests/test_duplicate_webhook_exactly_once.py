"""
Priority 10: replayed webhooks recover exactly once.

The pairwise cases are already covered in tests/test_payment_link_settlement.py -
duplicate payment_link.paid, link-then-captured, captured-then-link. Two things
they do not do, and both matter.

First, the ordering tests send a payment.captured body carrying
`payment_link_id`. Razorpay's real payment.captured does not. The ngrok
inspector for the live settlement on 2026-08-27 shows what actually arrived for
one payment, inside three seconds:

    20:29:52  payment.authorized   (new payment id, no link id)
    20:29:53  payment.captured     (new payment id, no link id)
    20:29:54  payment_link.paid    (link id + new payment id)

So in production the captured event arrives *first* and cannot settle anything,
and payment_link.paid does the work a second later. That sequence had no test.

Second, both "exactly once" tests re-implement the aggregation inline with their
own query. `get_dashboard_metrics` - the function the dashboard and the judges
actually read - is imported by one test and never called. A double-count living
in the real aggregation would go unnoticed by every existing test.

The four-record fixture from Priority 8 is reused so that "no other record is
affected" is a real assertion throughout.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest

from app import ledger, settlement
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.routes import metrics as metrics_route

from test_link_correlation_isolation import (  # noqa: F401 - `many` is a fixture
    A, B, C, D, AMOUNT, NEW_PAYMENT, PLINK_A, PLINK_B, PLINK_C, PLINK_D,
    link_of, many, payload, state, transitions,
)

RECOVERED_TRANSITION = "STATE_INTERVENING_TO_RECOVERED"


def captured_payload(payment_id=NEW_PAYMENT, amount=AMOUNT, currency="INR",
                     link_id=None):
    """
    A payment.captured body. `link_id` defaults to absent, which is what
    Razorpay actually sends - the correlation has to come from elsewhere.
    """
    entity = {"id": payment_id, "amount": amount, "currency": currency}
    if link_id:
        entity["payment_link_id"] = link_id
    return {"event": "payment.captured", "payload": {"payment": {"entity": entity}}}


@pytest.fixture
def dashboard(db_session, monkeypatch):
    """
    The real metrics function, bound to the test session.

    It opens its own session and closes it in a finally block, so close is
    neutered here the same way the webhook route tests do it.
    """
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(metrics_route, "SessionLocal", lambda: db_session)

    async def read():
        return await metrics_route.get_dashboard_metrics()

    return read


def recovery_entries(db, payment_id=None):
    q = db.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == RECOVERED_TRANSITION)
    if payment_id:
        q = q.filter(AuditTrailEntry.payment_id == payment_id)
    return q.count()


# --- The sequence Razorpay actually sends -----------------------------------


@pytest.mark.asyncio
async def test_the_real_delivery_sequence_settles_once(db_session, many):
    """captured (no link id) arrives first and settles nothing; link.paid does."""
    early = await settlement.handle_payment_captured(
        db_session, NEW_PAYMENT, captured_payload())

    # Nothing to match: the id is the new payment, and there is no link id.
    assert early["status"] == "not_found"
    assert transitions(db_session) == 0
    assert db_session.query(AuditTrailEntry).count() == 0
    assert state(db_session, B) == "INTERVENING"

    settled = await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))

    assert settled["status"] == "recovered"
    assert settled["payment_id"] == B
    assert state(db_session, B) == "RECOVERED"
    assert transitions(db_session) == 1


@pytest.mark.asyncio
async def test_replaying_the_whole_sequence_changes_nothing(db_session, many):
    await settlement.handle_payment_captured(db_session, NEW_PAYMENT, captured_payload())
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))

    after_first = db_session.query(AuditTrailEntry).count()
    assert transitions(db_session) == 1

    # Razorpay redelivers everything, repeatedly and out of order.
    for _ in range(3):
        await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
        await settlement.handle_payment_captured(
            db_session, NEW_PAYMENT, captured_payload())
        await settlement.handle_payment_captured(
            db_session, NEW_PAYMENT, captured_payload(link_id=PLINK_B))

    assert transitions(db_session) == 1
    assert recovery_entries(db_session, B) == 1
    assert db_session.query(AuditTrailEntry).count() == after_first
    assert state(db_session, B) == "RECOVERED"

    # One link row, settled once, pointing at one payment.
    assert db_session.query(RazorpayPaymentLink).filter(
        RazorpayPaymentLink.payment_id == B).count() == 1
    link = link_of(db_session, PLINK_B)
    assert link.status == "paid"
    assert link.razorpay_payment_id == NEW_PAYMENT


# --- The real metrics function ----------------------------------------------


@pytest.mark.asyncio
async def test_the_dashboard_counts_the_recovery_exactly_once(
        db_session, many, dashboard):
    """
    Reads `get_dashboard_metrics` itself rather than re-implementing the sum.
    A duplicate row from a join in the real aggregation is invisible to a test
    that writes its own query.
    """
    before = await dashboard()
    assert before["recovered_count"] == 0
    assert before["recovered_gmv"] == 0

    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    once = await dashboard()

    assert once["recovered_count"] == 1
    assert once["recovered_gmv"] == AMOUNT

    for _ in range(5):
        await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
        await settlement.handle_payment_captured(
            db_session, NEW_PAYMENT, captured_payload())

    after = await dashboard()

    assert after["recovered_count"] == 1
    assert after["recovered_gmv"] == AMOUNT
    assert after["total_records"] == once["total_records"]
    assert after["total_gmv"] == once["total_gmv"]
    assert after["total_channel_cost_paise"] == once["total_channel_cost_paise"]
    assert after["ledger"]["entries"] == once["ledger"]["entries"]
    assert after["ledger"]["head_hash"] == once["ledger"]["head_hash"]


@pytest.mark.asyncio
async def test_the_dashboard_and_the_database_agree(db_session, many, dashboard):
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))

    reported = await dashboard()
    rows = db_session.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.recovery_state == "RECOVERED").all()

    assert reported["recovered_count"] == len(rows) == 1
    assert reported["recovered_gmv"] == sum(r.amount for r in rows) == AMOUNT


# --- Isolation and integrity under replay -----------------------------------


@pytest.mark.asyncio
async def test_replays_never_reach_another_record(db_session, many):
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))

    for _ in range(3):
        await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
        await settlement.handle_payment_captured(
            db_session, NEW_PAYMENT, captured_payload())
        # A replay naming a link that was never created.
        await settlement.handle_payment_link_paid(db_session, payload("plink_GHOST"))

    for other in (A, C, D):
        assert state(db_session, other) == "INTERVENING", other
        assert db_session.query(AuditTrailEntry).filter(
            AuditTrailEntry.payment_id == other).count() == 0, other
        assert recovery_entries(db_session, other) == 0

    for plink in (PLINK_A, PLINK_C, PLINK_D):
        assert link_of(db_session, plink).status == "created"


@pytest.mark.asyncio
async def test_two_records_settle_independently_under_replay(db_session, many):
    """Replaying one settlement must not disturb another that already happened."""
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    await settlement.handle_payment_link_paid(
        db_session, payload(PLINK_C, payment_id="pay_NEW_C0001"))

    for _ in range(3):
        await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
        await settlement.handle_payment_link_paid(
            db_session, payload(PLINK_C, payment_id="pay_NEW_C0001"))

    assert transitions(db_session) == 2
    assert recovery_entries(db_session, B) == 1
    assert recovery_entries(db_session, C) == 1
    assert link_of(db_session, PLINK_B).razorpay_payment_id == NEW_PAYMENT
    assert link_of(db_session, PLINK_C).razorpay_payment_id == "pay_NEW_C0001"
    assert state(db_session, A) == "INTERVENING"
    assert state(db_session, D) == "INTERVENING"


@pytest.mark.asyncio
async def test_the_ledger_stays_valid_under_replay(db_session, many):
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    for _ in range(4):
        await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
        await settlement.handle_payment_captured(
            db_session, NEW_PAYMENT, captured_payload())

    result = ledger.verify_chain(db_session)

    assert result.valid is True, result.reason
    assert result.entries_checked == db_session.query(AuditTrailEntry).count()
    assert recovery_entries(db_session) == 1
