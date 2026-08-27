"""
Priority 8: the Payment Link is what decides which record a payment settles.

tests/test_payment_link_settlement.py covers this path thoroughly - happy path,
unknown link, amount and currency mismatch, conflicting notes, duplicate
delivery, event ordering. Every one of those tests runs against a database
holding exactly one record and exactly one link.

That is the hole. With a single candidate in the table, an implementation that
resolved the record by `.first()`, or by matching the captured amount, or by
taking the most recent open failure, passes all of it. None of those would be
correlation; all of them would be guessing, and the guess only becomes visible
when there is more than one plausible answer.

So this file builds a database where guessing is guaranteed to be wrong:

  A, B, C   identical amount, identical currency, identical failure class, all
            INTERVENING, inserted in a known order so "most recent" is a
            distinguishable - and incorrect - answer.
  D         a different amount, so an amount-based search has somewhere else to
            land when a settlement does not add up.

Each has its own link. The new payment id in every webhook is one the database
has never seen, except where a test deliberately collides it with a *different*
record's id to prove that is ignored too.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest

from app import ledger, settlement
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink

AMOUNT = 450000
ODD_AMOUNT = 999999

# original payment id, plink id, amount
FIXTURES = [
    ("pay_ORIG_A0000001", "plink_AAAAAAAAAAA1", AMOUNT),
    ("pay_ORIG_B0000002", "plink_BBBBBBBBBBB2", AMOUNT),
    ("pay_ORIG_C0000003", "plink_CCCCCCCCCCC3", AMOUNT),
    ("pay_ORIG_D0000004", "plink_DDDDDDDDDDD4", ODD_AMOUNT),
]

A, B, C, D = (f[0] for f in FIXTURES)
PLINK_A, PLINK_B, PLINK_C, PLINK_D = (f[1] for f in FIXTURES)

# Never a payment id the database already holds.
NEW_PAYMENT = "pay_NEW_SETTLEMENT01"


@pytest.fixture
def many(db_session, payment_record):
    """Four open failures, each with the link created for it."""
    built = {}
    for index, (payment_id, plink, amount) in enumerate(FIXTURES):
        record = payment_record(
            payment_id=payment_id,
            amount=amount,
            customer_phone=f"+91987650{index:04d}",
            failure_class="AUTH_FRICTION",
            recovery_state="INTERVENING",
            recovery_channel="whatsapp_link",
        )
        db_session.add(record)
        db_session.commit()

        link = RazorpayPaymentLink(
            payment_id=payment_id,
            recovery_action_id=f"{index}" * 64,
            razorpay_payment_link_id=plink,
            status="created",
            amount=amount,
            currency="INR",
        )
        db_session.add(link)
        db_session.commit()
        built[payment_id] = (record, link)

    return built


def payload(link_id, payment_id=NEW_PAYMENT, amount=AMOUNT, currency="INR", notes=None):
    entity = {"id": payment_id, "amount": amount, "currency": currency}
    if notes is not None:
        entity["notes"] = notes
    return {
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {"entity": {"id": link_id, "status": "paid"}},
            "payment": {"entity": entity},
        },
    }


def state(db, payment_id):
    return db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.payment_id == payment_id).one().recovery_state


def link_of(db, plink):
    return db.query(RazorpayPaymentLink).filter(
        RazorpayPaymentLink.razorpay_payment_link_id == plink).one()


def transitions(db, payment_id=None):
    q = db.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "STATE_INTERVENING_TO_RECOVERED")
    if payment_id:
        q = q.filter(AuditTrailEntry.payment_id == payment_id)
    return q.count()


# --- The premise ------------------------------------------------------------


def test_the_fixture_makes_guessing_wrong(db_session, many):
    """
    Guards the setup itself. If A, B and C ever stop being indistinguishable by
    amount, the tests below would still pass while proving much less.
    """
    amounts = {r.amount for r, _ in (many[A], many[B], many[C])}
    assert amounts == {AMOUNT}, "A, B and C must be indistinguishable by amount"
    assert many[D][0].amount == ODD_AMOUNT
    assert {state(db_session, p) for p in (A, B, C, D)} == {"INTERVENING"}
    assert db_session.query(RazorpayPaymentLink).count() == 4
    # The settling payment is not any record's id.
    assert db_session.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.payment_id == NEW_PAYMENT).count() == 0


# --- One link, one record ---------------------------------------------------


@pytest.mark.asyncio
async def test_settling_one_link_recovers_only_its_own_record(db_session, many):
    result = await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))

    assert result["status"] == "recovered"
    assert result["payment_id"] == B

    assert state(db_session, B) == "RECOVERED"
    assert state(db_session, A) == "INTERVENING"
    assert state(db_session, C) == "INTERVENING"
    assert state(db_session, D) == "INTERVENING"

    assert transitions(db_session) == 1
    assert transitions(db_session, B) == 1

    # Only B's link moved.
    assert link_of(db_session, PLINK_B).status == "paid"
    assert link_of(db_session, PLINK_B).razorpay_payment_id == NEW_PAYMENT
    for plink in (PLINK_A, PLINK_C, PLINK_D):
        assert link_of(db_session, plink).status == "created"
        assert link_of(db_session, plink).razorpay_payment_id is None

    # Nothing was written against the records that were not settled.
    for other in (A, C, D):
        assert db_session.query(AuditTrailEntry).filter(
            AuditTrailEntry.payment_id == other).count() == 0


@pytest.mark.asyncio
async def test_the_oldest_link_settles_the_oldest_record(db_session, many):
    """
    A is the first record inserted and C the last. Settling A's link must
    recover A - "most recently seen open failure" is a plausible-looking rule
    and the wrong one.
    """
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_A))

    assert state(db_session, A) == "RECOVERED"
    assert state(db_session, C) == "INTERVENING"


@pytest.mark.asyncio
async def test_every_link_settles_its_own_record(db_session, many):
    """Settled out of insertion order, to rule out an index-based coincidence."""
    for plink, owner, amount in (
        (PLINK_C, C, AMOUNT), (PLINK_A, A, AMOUNT), (PLINK_D, D, ODD_AMOUNT),
    ):
        result = await settlement.handle_payment_link_paid(
            db_session, payload(plink, payment_id=f"pay_NEW_{owner[-4:]}", amount=amount))
        assert result["payment_id"] == owner, plink

    assert state(db_session, A) == "RECOVERED"
    assert state(db_session, C) == "RECOVERED"
    assert state(db_session, D) == "RECOVERED"
    assert state(db_session, B) == "INTERVENING"
    assert transitions(db_session) == 3

    for plink, owner in ((PLINK_C, C), (PLINK_A, A), (PLINK_D, D)):
        assert link_of(db_session, plink).payment_id == owner
        assert link_of(db_session, plink).razorpay_payment_id == f"pay_NEW_{owner[-4:]}"


# --- No guessing ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_new_payment_id_colliding_with_another_record_is_ignored(db_session, many):
    """
    The webhook's payment id is the *new* payment. Here it is set to C's
    original id, which a direct id match would seize on. The link says B.
    """
    result = await settlement.handle_payment_link_paid(
        db_session, payload(PLINK_B, payment_id=C))

    assert result["payment_id"] == B
    assert state(db_session, B) == "RECOVERED"
    assert state(db_session, C) == "INTERVENING"
    assert link_of(db_session, PLINK_B).razorpay_payment_id == C


@pytest.mark.asyncio
async def test_an_amount_that_matches_a_different_record_does_not_settle_it(
        db_session, many):
    """
    B's link is paid an amount that is not B's but *is* D's. The correct
    outcome is a refusal on B and no interest whatsoever in D.
    """
    result = await settlement.handle_payment_link_paid(
        db_session, payload(PLINK_B, amount=ODD_AMOUNT))

    assert result["status"] == "mismatch"
    assert state(db_session, B) == "INTERVENING"
    assert state(db_session, D) == "INTERVENING"
    assert transitions(db_session) == 0

    held = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "SETTLEMENT_MISMATCH_HELD").one()
    assert held.payment_id == B
    assert "WHY_WE_DIDNT_ACT" in held.details
    assert db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.payment_id == D).count() == 0

    # The link is left unsettled, so a corrected delivery can still land.
    assert link_of(db_session, PLINK_B).status == "created"


@pytest.mark.asyncio
async def test_notes_naming_another_record_are_disqualifying(db_session, many):
    """A body claiming one record while the link says another settles neither."""
    result = await settlement.handle_payment_link_paid(
        db_session, payload(PLINK_A, notes={"recoveros_payment_id": C}))

    assert result["status"] == "mismatch"
    assert state(db_session, A) == "INTERVENING"
    assert state(db_session, C) == "INTERVENING"
    assert transitions(db_session) == 0


@pytest.mark.asyncio
async def test_a_link_this_system_never_created_recovers_nothing(db_session, many):
    before = db_session.query(AuditTrailEntry).count()

    result = await settlement.handle_payment_link_paid(
        db_session, payload("plink_NEVER_CREATED"))

    assert result["status"] == "not_found"
    assert {state(db_session, p) for p in (A, B, C, D)} == {"INTERVENING"}
    assert transitions(db_session) == 0
    # Nothing durable at all: there is no record to attribute an entry to.
    assert db_session.query(AuditTrailEntry).count() == before


# --- Duplicates -------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_delivery_is_a_no_op_and_leaves_the_others_alone(
        db_session, many):
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    after_first = db_session.query(AuditTrailEntry).count()

    second = await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    third = await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))

    assert second["status"] == "already_recovered"
    assert third["status"] == "already_recovered"
    assert second["payment_id"] == B
    assert transitions(db_session) == 1
    assert db_session.query(AuditTrailEntry).count() == after_first
    assert state(db_session, A) == "INTERVENING"
    assert state(db_session, C) == "INTERVENING"


# --- Ledger -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_ledger_stays_valid_across_mixed_outcomes(db_session, many):
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))
    await settlement.handle_payment_link_paid(db_session, payload("plink_NEVER"))
    await settlement.handle_payment_link_paid(
        db_session, payload(PLINK_A, amount=ODD_AMOUNT))
    await settlement.handle_payment_link_paid(
        db_session, payload(PLINK_C, payment_id="pay_NEW_C0001"))

    result = ledger.verify_chain(db_session)

    assert result.valid is True, result.reason
    assert result.entries_checked == db_session.query(AuditTrailEntry).count()
    assert transitions(db_session) == 2          # B and C, once each
    assert state(db_session, A) == "INTERVENING"  # held on the mismatch
    assert state(db_session, D) == "INTERVENING"  # never addressed
