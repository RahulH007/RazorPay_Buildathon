"""
Exactly once, under duplicates and races.

Razorpay retries webhook delivery on any non-2xx and on a timeout, fires
payment.captured and payment_link.paid for the same rupee, and will happily
deliver both at the same moment. Meanwhile the recovery tick is an endpoint
anyone can call twice, and nothing stopped two of them from working the same
record. Every one of those is ordinary operation, not an edge case.

Before this file, the protections were all read-then-write:

    if record.recovery_state in ("INTERVENING", "DIAGNOSED"): transition(...)
    if link.status == "paid": return already_recovered
    if existing: return duplicate
    attempts = count_attempts(db, record)   # then decide, then act

Each is correct in a single thread and none of them is atomic. Two callers
holding their own sessions both read the open state, both pass the check, and
both act - two ledger transitions for one payment, or two Payment Links and two
WhatsApp messages to one customer.

How these tests reproduce that
------------------------------
Two Sessions on one connection, each holding its own identity map and its own
loaded copy of the record, with expire_on_commit off so a worker's view stays
as stale as a separate process's would be. The first acts and commits; the
second then acts on the view it already had. That is precisely the interleaving
a second webhook delivery or a second tick produces, it is deterministic rather
than timing-dependent, and it fails against read-then-write code every time.

A note on asyncio.gather, because it is a trap here. Awaiting a coroutine does
not yield unless something inside it genuinely suspends, and neither the
settlement path nor the executor does on its own - so gather alone runs them
one after the other and proves nothing about concurrency. Where a real overlap
is needed, these tests create one explicitly: `in_flight` holds a worker inside
its action on an asyncio.Event, and the settlement tests hand the second caller
a record it loaded before the first acted. Both are deterministic, and both
fail against read-then-write code.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import (
    event_adapter, idempotency, ledger, recovery_actions, recovery_tick, settlement,
)
from app.database import Base
from app.models import (
    AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink, RecoveryAttemptClaim,
)
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.state_machine import VALID_TRANSITIONS, transition_state

LINK_ID = "plink_race_0001"
NEW_PAYMENT = "pay_new_race_0001"
AMOUNT = 45_000


# --- Two workers, one database ----------------------------------------------


@pytest.fixture
def shared():
    """
    One database, two independent sessions.

    StaticPool keeps them on a single connection so neither can block the
    other - this file is about the read-then-write window, not about SQLite's
    lock manager. expire_on_commit is off so a session's loaded record stays
    stale after the other commits, which is exactly what a second process
    holding a record it read a moment ago looks like.
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    a, b = factory(), factory()
    try:
        yield a, b
    finally:
        a.close()
        b.close()
        Base.metadata.drop_all(bind=engine)


def seed(db, *, payment_id="pay_race", state="INTERVENING", failure_class="AUTH_FRICTION",
         source=LIVE_SOURCE, batch_id=None, error_reason="authentication_failed",
         invoice_id=None):
    record = PaymentFailureRecord(
        payment_id=payment_id, amount=AMOUNT, currency="INR", method="upi",
        merchant_id="m", customer_name="Race Customer",
        customer_phone="+919999999999", error_reason=error_reason,
        error_description="d", failure_class=failure_class,
        recovery_state=state, source=source, batch_id=batch_id,
        invoice_id=invoice_id, arm="treated",
    )
    db.add(record)
    db.commit()
    return record


def seed_link(db, record, link_id=LINK_ID):
    link = RazorpayPaymentLink(
        payment_id=record.payment_id, recovery_action_id="a" * 64,
        razorpay_payment_link_id=link_id, status="created",
        amount=record.amount, currency="INR",
    )
    db.add(link)
    db.commit()
    return link


def link_paid_payload(link_id=LINK_ID, payment_id=NEW_PAYMENT, amount=AMOUNT):
    return {
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {"entity": {"id": link_id}},
            "payment": {"entity": {"id": payment_id, "amount": amount,
                                   "currency": "INR", "notes": {}}},
        },
    }


def failed_payload(payment_id="pay_dupe_webhook", reason="authentication_failed"):
    return {
        "event": "payment.failed",
        "account_id": "acc_test",
        "payload": {"payment": {"entity": {
            "id": payment_id, "amount": AMOUNT, "currency": "INR", "method": "upi",
            "contact": "+919999999999", "error_reason": reason,
            "error_description": "d", "error_source": "customer",
            "error_step": "authentication",
        }}},
    }


def actions(db, payment_id=None):
    query = db.query(AuditTrailEntry)
    if payment_id:
        query = query.filter(AuditTrailEntry.payment_id == payment_id)
    return [e.action for e in query.order_by(AuditTrailEntry.sequence_no)]


def recovered_transitions(db, payment_id):
    return [a for a in actions(db, payment_id) if a.endswith("_TO_RECOVERED")]


def reload(db, payment_id):
    db.expire_all()
    return db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.payment_id == payment_id).first()


async def _template(record, link_url):
    """Keep the executor off the model and off the cache."""
    return f"template for {record.customer_name}", {}, None


@pytest.fixture(autouse=True)
def no_generation(monkeypatch):
    monkeypatch.setattr(recovery_actions, "generate_whatsapp_message", _template)


def in_flight(monkeypatch, channel="whatsapp_link"):
    """
    Hold one worker inside its action so another can decide beside it.

    This is the window that matters and the only one worth testing. Counting
    attempts off the ledger already stops a worker that decides *after* another
    has sent - what it cannot stop is a worker that decides while the first is
    still in flight, which is what every real duplicate looks like: a tick
    firing during the 300ms a Razorpay Payment Link takes to create.

    Returns (started, release). The first worker sets `started` on entering the
    action and blocks until `release` is set, so the second worker's entire
    decide-guard-claim sequence runs against a ledger showing no attempt.
    """
    started, release = asyncio.Event(), asyncio.Event()
    real = recovery_actions.CHANNEL_ACTION_MAP[channel]

    async def held(db, rec, source=None):
        started.set()
        await release.wait()
        return await real(db, rec, source=source)

    monkeypatch.setitem(recovery_actions.CHANNEL_ACTION_MAP, channel, held)
    return started, release


async def race(first, second, started, release):
    """Run `second` entirely inside `first`'s in-flight action."""
    async def follower():
        # Both waits are bounded. Neither should ever fire against working
        # code - the first worker always reaches its action and the second
        # always returns - but an unbounded wait turns a broken claim into a
        # hung test suite instead of a failing assertion, which is the one
        # outcome a concurrency test must never produce.
        await asyncio.wait_for(started.wait(), timeout=5)
        try:
            # Bounded on purpose. If the second worker is ever allowed into the
            # action it will block on a release only it can trigger, and the
            # test would hang instead of failing. A watchdog turns that into a
            # loud TimeoutError, which is what a broken claim should look like.
            return await asyncio.wait_for(second(), timeout=5)
        finally:
            release.set()

    return await asyncio.gather(first(), follower())


# =============================================================================
# Duplicate and concurrent ingestion
# =============================================================================


@pytest.mark.asyncio
async def test_a_duplicate_identical_webhook_ingests_once(shared):
    a, _ = shared
    normalized = event_adapter.normalize_razorpay_payment_failed(failed_payload())

    first = await event_adapter.ingest_and_process(a, dict(normalized))
    second = await event_adapter.ingest_and_process(a, dict(normalized))

    assert first["status"] == "ingested"
    assert second["status"] == "duplicate"
    assert a.query(PaymentFailureRecord).count() == 1
    assert actions(a, "pay_dupe_webhook").count("RECORD_INGESTED") == 1


@pytest.mark.asyncio
async def test_a_delivery_whose_existence_check_missed_still_ingests_once(
        shared, monkeypatch):
    """
    The window inside ingest_and_process: both deliveries SELECT before either
    INSERTs, so both pass the existence check and both try to write the record.

    Reproduced by making the second delivery's lookup miss, which is precisely
    what a sibling transaction that has not committed yet looks like from
    another connection. The primary key is what stops a second row; what this
    test is for is that the loser loses *cleanly* - reported as a duplicate,
    with a usable session - rather than surfacing as an unhandled IntegrityError
    in the webhook log.
    """
    a, b = shared
    normalized = event_adapter.normalize_razorpay_payment_failed(failed_payload())
    first = await event_adapter.ingest_and_process(a, dict(normalized))

    real_query = b.query
    missed = {"once": False}

    def blind_first_lookup(*args, **kwargs):
        if args and args[0] is PaymentFailureRecord and not missed["once"]:
            missed["once"] = True

            class Miss:
                def filter(self, *a, **k):
                    return self

                def first(self):
                    return None

            return Miss()
        return real_query(*args, **kwargs)

    monkeypatch.setattr(b, "query", blind_first_lookup)

    second = await event_adapter.ingest_and_process(b, dict(normalized))

    assert missed["once"] is True                     # the check really did miss
    assert first["status"] == "ingested"
    assert second["status"] == "duplicate"
    assert second["recovery_state"] is not None       # the session still works
    assert a.query(PaymentFailureRecord).count() == 1
    assert actions(a, "pay_dupe_webhook").count("RECORD_INGESTED") == 1


# =============================================================================
# Exactly one recovery action
# =============================================================================


@pytest.mark.asyncio
async def test_two_workers_on_one_record_send_exactly_one_message(shared, monkeypatch):
    """
    THE double-contact test. Worker B decides while worker A is still inside
    its action, so B counts zero attempts on the ledger, is approved for rung
    one, and is authorised by the guard - every read-based defence passes.
    Exactly one message is sent, one Payment Link row exists, 50 paise is spent.
    """
    a, b = shared
    seed(a, payment_id="pay_two_workers", state="DIAGNOSED")
    from_a = a.query(PaymentFailureRecord).filter_by(payment_id="pay_two_workers").one()
    from_b = b.query(PaymentFailureRecord).filter_by(payment_id="pay_two_workers").one()
    started, release = in_flight(monkeypatch)

    first, second = await race(
        lambda: recovery_actions.execute_recovery(a, from_a, source=LIVE_SOURCE),
        lambda: recovery_actions.execute_recovery(b, from_b, source=LIVE_SOURCE),
        started, release,
    )

    assert first["action"] == "whatsapp_link"
    assert second["action"] == "no_action"
    assert second["reason_code"] == idempotency.DUPLICATE_REASON_CODE
    assert actions(a, "pay_two_workers").count("WHATSAPP_LINK_SENT") == 1
    assert sum(e.cost_paise or 0 for e in a.query(AuditTrailEntry)) == 50


@pytest.mark.asyncio
async def test_a_decision_taken_before_another_worker_acted_cannot_be_used(shared):
    """
    The same window, reduced to the primitive. B's decision names attempt 0 and
    was taken while that was true; by the time B would act, A has made attempt
    0. The claim is what refuses it - re-counting attempts would not, because B
    is not re-counting, it is acting on a decision it already holds.
    """
    from app import policy

    a, b = shared
    seed(a, payment_id="pay_stale_decision", state="DIAGNOSED")
    from_a = a.query(PaymentFailureRecord).filter_by(
        payment_id="pay_stale_decision").one()
    from_b = b.query(PaymentFailureRecord).filter_by(
        payment_id="pay_stale_decision").one()

    stale_decision = policy.decide_next_action(b, from_b)
    assert stale_decision.attempt_number == 0

    await recovery_actions.execute_recovery(a, from_a, source=LIVE_SOURCE)

    assert idempotency.claim_attempt(b, from_b, stale_decision.attempt_number) is False
    assert actions(a, "pay_stale_decision").count("WHATSAPP_LINK_SENT") == 1


@pytest.mark.asyncio
async def test_two_ticks_racing_the_same_record_act_once(shared, monkeypatch):
    """
    The endpoint anyone can call twice, called twice at once. The second tick
    selects the record as due - correctly, since no attempt is on the ledger
    yet - and is stopped at the claim rather than at the message.
    """
    a, b = shared
    seed(a, payment_id="pay_two_ticks", state="DIAGNOSED")
    started, release = in_flight(monkeypatch)

    results = await race(
        lambda: recovery_tick.advance_open_recoveries(a),
        lambda: recovery_tick.advance_open_recoveries(b),
        started, release,
    )

    assert sum(len(r["failed"]) for r in results) == 0
    assert results[1]["due"] == ["pay_two_ticks"]          # it really was selected
    assert actions(a, "pay_two_ticks").count("WHATSAPP_LINK_SENT") == 1


@pytest.mark.asyncio
async def test_the_second_attempt_is_claimable_once_the_first_has_landed(shared):
    """
    Suppression must be exactly-once, not once-ever. The ladder still escalates:
    a genuine second attempt carries a different attempt number and claims
    cleanly.
    """
    a, _ = shared
    record = seed(a, payment_id="pay_ladder", state="DIAGNOSED")

    first = await recovery_actions.execute_recovery(a, record, source=LIVE_SOURCE)
    second = await recovery_actions.execute_recovery(a, record, source=LIVE_SOURCE)

    assert first["action"] == second["action"] == "whatsapp_link"
    assert actions(a, "pay_ladder").count("WHATSAPP_LINK_SENT") == 2
    assert {c.attempt_number for c in a.query(RecoveryAttemptClaim)} == {0, 1}


@pytest.mark.asyncio
async def test_a_claim_is_scoped_to_its_batch_so_a_rerun_can_act_again(shared):
    """
    The ledger is append-only and the simulator re-runs the same payment ids
    under a new batch id. A claim keyed on payment and attempt alone would make
    every record in the second run look already-claimed and kill the demo.
    """
    a, _ = shared
    record = seed(a, payment_id="pay_rerun", state="DIAGNOSED",
                  source=SYNTHETIC_SOURCE, batch_id="batch_one")

    await recovery_actions.execute_recovery(a, record, source=SYNTHETIC_SOURCE)

    record.batch_id = "batch_two"
    record.recovery_state = "DIAGNOSED"
    a.commit()
    again = await recovery_actions.execute_recovery(a, record, source=SYNTHETIC_SOURCE)

    assert again["action"] == "whatsapp_link"
    assert {c.batch_key for c in a.query(RecoveryAttemptClaim)} == {"batch_one", "batch_two"}


def test_an_absent_batch_id_still_makes_a_claim_unique(shared):
    """
    SQL treats NULLs as distinct, so a UNIQUE index over a nullable batch_id
    would let every live record - all of which carry no batch - be claimed
    twice. The sentinel is what closes that, and it is the whole live path.
    """
    a, _ = shared
    record = seed(a, payment_id="pay_null_batch", batch_id=None)

    assert idempotency.batch_key(record) == idempotency.NO_BATCH
    assert idempotency.claim_attempt(a, record, 0) is True
    assert idempotency.claim_attempt(a, record, 0) is False
    assert a.query(RecoveryAttemptClaim).count() == 1


# =============================================================================
# Exactly one RECOVERED transition, and one lot of revenue
# =============================================================================


@pytest.mark.asyncio
async def test_two_payment_captured_webhooks_recover_once(shared):
    a, b = shared
    seed(a, payment_id="pay_cap_twice")

    first = await settlement.handle_payment_captured(a, "pay_cap_twice", {})
    second = await settlement.handle_payment_captured(b, "pay_cap_twice", {})

    assert first["status"] == "recovered"
    assert second["status"] == "already_recovered"
    assert recovered_transitions(a, "pay_cap_twice") == ["STATE_INTERVENING_TO_RECOVERED"]


@pytest.mark.asyncio
async def test_a_second_payment_captured_delivery_that_read_early_recovers_once(shared):
    """
    The real duplicate, not a sequential one.

    B loaded this record before A settled it, so B's own lookup returns the
    copy it already holds - still saying INTERVENING - and B sails past the
    `already RECOVERED` early check straight into the transition. That is
    exactly what a delivery whose SELECT landed a moment before the other
    delivery's UPDATE looks like, and read-then-write puts a second RECOVERED
    on an append-only chain for one payment.
    """
    a, b = shared
    seed(a, payment_id="pay_cap_race")
    early = b.query(PaymentFailureRecord).filter_by(payment_id="pay_cap_race").one()

    first = await settlement.handle_payment_captured(a, "pay_cap_race", {})
    assert early.recovery_state == "INTERVENING"        # B's view is genuinely stale

    second = await settlement.handle_payment_captured(b, "pay_cap_race", {})

    assert first["status"] == "recovered"
    assert second["status"] == "already_recovered"
    assert len(recovered_transitions(a, "pay_cap_race")) == 1


@pytest.mark.asyncio
async def test_payment_captured_and_payment_link_paid_arriving_together_recover_once(
        shared):
    """
    Razorpay's own pairing. One rupee, two event types, two code paths into the
    same record - and historically two transitions when they landed at once.
    """
    a, b = shared
    record = seed(a, payment_id="pay_both_events")
    seed_link(a, record)
    # The payment.captured handler read the record before payment_link.paid
    # settled it - the ordinary case when Razorpay emits both at once.
    early = b.query(PaymentFailureRecord).filter_by(payment_id="pay_both_events").one()

    link_result = await settlement.handle_payment_link_paid(a, link_paid_payload())
    assert early.recovery_state == "INTERVENING"

    captured_result = await settlement.handle_payment_captured(b, "pay_both_events", {})

    assert link_result["status"] == "recovered"
    assert captured_result["status"] == "already_recovered"
    assert len(recovered_transitions(a, "pay_both_events")) == 1
    assert reload(a, "pay_both_events").recovery_state == "RECOVERED"


@pytest.mark.asyncio
async def test_two_payment_link_paid_webhooks_settle_the_link_once(shared):
    a, b = shared
    record = seed(a, payment_id="pay_link_twice")
    seed_link(a, record)

    first = await settlement.handle_payment_link_paid(a, link_paid_payload())
    second = await settlement.handle_payment_link_paid(b, link_paid_payload())

    assert first["status"] == "recovered"
    assert second["status"] == "already_recovered"
    assert len(recovered_transitions(a, "pay_link_twice")) == 1
    assert a.query(RazorpayPaymentLink).filter_by(status="paid").count() == 1


@pytest.mark.asyncio
async def test_a_stale_link_row_cannot_be_settled_a_second_time(shared):
    """
    The link's own read-then-write. B holds a copy that still says "created"
    after A has marked it paid, and the conditional update is what refuses it.
    """
    a, b = shared
    record = seed(a, payment_id="pay_stale_link")
    seed_link(a, record)
    stale_link = b.query(RazorpayPaymentLink).filter_by(
        razorpay_payment_link_id=LINK_ID).one()

    await settlement.handle_payment_link_paid(a, link_paid_payload())

    assert stale_link.status == "created"      # genuinely stale
    result = await settlement._settle_via_payment_link(
        b, link=stale_link, new_payment_id="pay_second_capture",
        amount=AMOUNT, currency="INR", notes={})

    assert result["status"] == "already_recovered"
    assert len(recovered_transitions(a, "pay_stale_link")) == 1


@pytest.mark.asyncio
async def test_two_invoice_paid_webhooks_recover_once(shared):
    a, b = shared
    seed(a, payment_id="pay_invoice", failure_class="B2B_RECEIVABLE",
         error_reason="invoice_overdue_15d", invoice_id="inv_race_01")

    early = b.query(PaymentFailureRecord).filter_by(payment_id="pay_invoice").one()

    first = await settlement.handle_invoice_paid(a, "inv_race_01", {})
    assert early.recovery_state == "INTERVENING"        # B's view is genuinely stale

    second = await settlement.handle_invoice_paid(b, "inv_race_01", {})

    assert first["status"] == "recovered"
    assert second["status"] == "already_recovered"
    assert len(recovered_transitions(a, "pay_invoice")) == 1


@pytest.mark.asyncio
async def test_recovered_revenue_is_counted_exactly_once(shared, monkeypatch):
    """
    The money question. Four settlement attempts across three code paths on one
    payment; the dashboard reports one recovery and one lot of GMV.
    """
    from app.routes import metrics as metrics_route

    a, b = shared
    record = seed(a, payment_id="pay_revenue")
    seed_link(a, record)

    await settlement.handle_payment_link_paid(a, link_paid_payload())
    await settlement.handle_payment_link_paid(b, link_paid_payload())
    await settlement.handle_payment_captured(a, "pay_revenue", {})
    await settlement.handle_payment_captured(b, "pay_revenue", {})

    monkeypatch.setattr(a, "close", lambda: None)
    monkeypatch.setattr(metrics_route, "SessionLocal", lambda: a)
    result = await metrics_route.get_dashboard_metrics(scope="live")

    assert result["recovered_count"] == 1
    assert result["recovered_gmv"] == AMOUNT
    assert len(recovered_transitions(a, "pay_revenue")) == 1


@pytest.mark.asyncio
async def test_a_lost_transition_is_reported_rather_than_silently_claimed(shared):
    """
    transition_state returns whether it won. Callers that report an outcome to
    Razorpay must not answer "recovered" for a transition somebody else made -
    that is how a duplicate delivery becomes a duplicate metric downstream.
    """
    a, b = shared
    seed(a, payment_id="pay_lost")
    stale = b.query(PaymentFailureRecord).filter_by(payment_id="pay_lost").one()

    won = await transition_state(a, reload(a, "pay_lost"), to_state="RECOVERED",
                                 actor="system", details="first")
    lost = await transition_state(b, stale, to_state="RECOVERED",
                                  actor="system", details="second")

    assert won is True
    assert lost is False
    assert len(recovered_transitions(a, "pay_lost")) == 1


# =============================================================================
# Retry after partial failure
# =============================================================================


@pytest.mark.asyncio
async def test_an_attempt_that_fails_before_contact_can_be_retried(shared, monkeypatch):
    """
    A claim must not become a tombstone. If the action blew up before anything
    reached the customer, nothing was spent and nothing was sent, so the next
    tick has to be able to try that same rung again.
    """
    a, _ = shared
    record = seed(a, payment_id="pay_retry", state="DIAGNOSED")
    real = recovery_actions.CHANNEL_ACTION_MAP["whatsapp_link"]

    async def explode(db, rec, source=None):
        raise RuntimeError("Razorpay timed out")

    monkeypatch.setitem(recovery_actions.CHANNEL_ACTION_MAP, "whatsapp_link", explode)
    with pytest.raises(RuntimeError):
        await recovery_actions.execute_recovery(a, record, source=LIVE_SOURCE)

    assert a.query(RecoveryAttemptClaim).count() == 0        # released
    assert actions(a, "pay_retry").count("WHATSAPP_LINK_SENT") == 0

    # Put back only this one entry. NOT monkeypatch.undo(): `monkeypatch` is a
    # single function-scoped instance shared with every fixture that requested
    # it, conftest's _no_external_apis included, so undo() disarms the whole
    # external-API isolation for the rest of the test. It did exactly that here
    # until a socket sentinel caught the resulting call to Razorpay.
    monkeypatch.setitem(recovery_actions.CHANNEL_ACTION_MAP, "whatsapp_link", real)
    retried = await recovery_actions.execute_recovery(a, record, source=LIVE_SOURCE)

    assert retried["action"] == "whatsapp_link"
    assert actions(a, "pay_retry").count("WHATSAPP_LINK_SENT") == 1


@pytest.mark.asyncio
async def test_an_attempt_that_fails_after_contact_is_not_retried_as_the_same_rung(
        shared, monkeypatch):
    """
    The other half, and the one that costs money to get wrong. If the message
    went out and the failure came afterwards, the customer has been contacted;
    releasing the claim would send them a second copy of the same message.
    """
    a, _ = shared
    record = seed(a, payment_id="pay_partial", state="DIAGNOSED")

    real = recovery_actions.send_whatsapp_link

    async def send_then_fail(db, rec, source=None):
        await real(db, rec, source=source)
        raise RuntimeError("crashed after sending")

    monkeypatch.setitem(recovery_actions.CHANNEL_ACTION_MAP, "whatsapp_link",
                        send_then_fail)
    with pytest.raises(RuntimeError):
        await recovery_actions.execute_recovery(a, record, source=LIVE_SOURCE)

    assert actions(a, "pay_partial").count("WHATSAPP_LINK_SENT") == 1
    claims = a.query(RecoveryAttemptClaim).all()
    assert [c.attempt_number for c in claims] == [0]         # kept, not released


@pytest.mark.asyncio
async def test_a_refused_attempt_holds_no_claim(shared):
    """
    A policy or guard refusal is not an attempt. Holding a claim for one would
    block the rung the moment the refusal stopped applying - a quiet-hours
    deferral would become permanent.
    """
    a, _ = shared
    record = seed(a, payment_id="pay_refused", state="DIAGNOSED",
                  failure_class="HARD_DECLINE", error_reason="compliance_violation")

    result = await recovery_actions.execute_recovery(a, record, source=LIVE_SOURCE)

    assert result["action"] == "declined"
    assert a.query(RecoveryAttemptClaim).count() == 0


# =============================================================================
# The chain, the FSM, and everything that must not have moved
# =============================================================================


@pytest.mark.asyncio
async def test_the_ledger_stays_valid_through_every_race(shared, monkeypatch):
    a, b = shared
    record = seed(a, payment_id="pay_chain", state="DIAGNOSED")
    seed_link(a, record)

    from_b = b.query(PaymentFailureRecord).filter_by(payment_id="pay_chain").one()
    started, release = in_flight(monkeypatch)
    await race(
        lambda: recovery_actions.execute_recovery(a, record, source=LIVE_SOURCE),
        lambda: recovery_actions.execute_recovery(b, from_b, source=LIVE_SOURCE),
        started, release,
    )
    await asyncio.gather(
        settlement.handle_payment_link_paid(a, link_paid_payload()),
        settlement.handle_payment_captured(b, "pay_chain", {}),
        return_exceptions=True,
    )

    chain = ledger.verify_chain(a)
    assert chain.valid is True, chain.reason
    assert chain.entries_checked == a.query(AuditTrailEntry).count()
    assert len(recovered_transitions(a, "pay_chain")) == 1


def test_no_new_fsm_state_was_introduced():
    assert set(VALID_TRANSITIONS) == {
        "INGESTED", "DIAGNOSED", "INTERVENING", "RECOVERED", "FAILED_STOPPED",
    }
    assert VALID_TRANSITIONS["RECOVERED"] == []
    assert VALID_TRANSITIONS["FAILED_STOPPED"] == []


@pytest.mark.asyncio
async def test_suppression_uses_a_verb_the_simulator_already_stops_on(
        shared, monkeypatch):
    """
    recovery_simulator loops until the record is terminal and breaks only on
    "declined" or "no_action". A new verb here would spin the demo forever, so
    the duplicate result reuses one the loop already understands and carries
    its own reason code for anyone reading the outcome.
    """
    a, b = shared
    seed(a, payment_id="pay_verb", state="DIAGNOSED", source=SYNTHETIC_SOURCE,
         batch_id="batch_verb")
    from_a = a.query(PaymentFailureRecord).filter_by(payment_id="pay_verb").one()
    from_b = b.query(PaymentFailureRecord).filter_by(payment_id="pay_verb").one()
    started, release = in_flight(monkeypatch)

    _, second = await race(
        lambda: recovery_actions.execute_recovery(a, from_a, source=SYNTHETIC_SOURCE),
        lambda: recovery_actions.execute_recovery(b, from_b, source=SYNTHETIC_SOURCE),
        started, release,
    )

    assert second["action"] in ("declined", "no_action")
    assert second["duplicate_suppressed"] is True


@pytest.mark.asyncio
async def test_an_uncontended_synthetic_run_behaves_exactly_as_before(shared):
    """
    The demo path is single-threaded and never contends, so every claim it
    makes must succeed. A full AUTH_FRICTION ladder walks to exhaustion with
    the same two sends and the same 100 paise it always cost.
    """
    a, _ = shared
    record = seed(a, payment_id="pay_synth", state="DIAGNOSED",
                  source=SYNTHETIC_SOURCE, batch_id="batch_synth")

    outcomes = []
    while record.recovery_state not in ("RECOVERED", "FAILED_STOPPED"):
        result = await recovery_actions.execute_recovery(a, record,
                                                         source=SYNTHETIC_SOURCE)
        outcomes.append(result["action"])
        if result["action"] in ("declined", "no_action"):
            break

    assert outcomes == ["whatsapp_link", "whatsapp_link", "declined"]
    assert actions(a, "pay_synth").count("WHATSAPP_LINK_SENT") == 2
    assert sum(e.cost_paise or 0 for e in a.query(AuditTrailEntry)) == 100
    assert record.recovery_state == "FAILED_STOPPED"


@pytest.mark.asyncio
async def test_nothing_here_reaches_an_external_api(shared):
    from app import llm_cache, voice_pipeline

    a, _ = shared
    record = seed(a, payment_id="pay_no_net", state="DIAGNOSED")
    await recovery_actions.execute_recovery(a, record, source=LIVE_SOURCE)

    assert llm_cache.DEMO_MODE is True
    assert voice_pipeline.DEMO_MODE is True
    assert a.query(RazorpayPaymentLink).count() == 0
