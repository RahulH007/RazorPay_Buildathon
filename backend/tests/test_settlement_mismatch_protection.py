"""
Priority 9: a settlement that does not add up is refused, ledgered, and leaves
everything exactly where it was.

The three refusals already have tests in tests/test_payment_link_settlement.py,
but they assert different amounts of the property. Only the amount case checks
that SETTLEMENT_MISMATCH_HELD was actually written; the currency and notes cases
assert that nothing recovered, which a silent refusal writing no ledger entry at
all would also satisfy. None of the three checks spend, none checks the ledger
still verifies, and none has another record present to be collaterally damaged.

So this file asserts the same seven properties for all three mismatch kinds,
against the four-record fixture from Priority 8 where a wrong answer has
somewhere to go:

    SETTLEMENT_MISMATCH_HELD written, naming why
    no RECOVERED transition anywhere
    the link stays created, with no payment id attached
    the record stays INTERVENING
    no extra spend
    no other record touched
    the ledger still verifies

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest

from app import ledger, settlement
from app.guardrails import spend_paise
from app.models import AuditTrailEntry, PaymentFailureRecord
from app.state_machine import log_audit

# The four-record fixture, so there is exactly one definition of "a database
# where guessing is wrong" rather than two that drift.
from test_link_correlation_isolation import (  # noqa: F401 - `many` is a fixture
    A, B, C, D, ODD_AMOUNT, PLINK_A, PLINK_B, PLINK_C, PLINK_D,
    link_of, many, payload, state, transitions,
)

HELD = "SETTLEMENT_MISMATCH_HELD"

# Each case targets B's link. The payload is wrong in exactly one way, and the
# wrongness always points at something real elsewhere in the database - D's
# amount, C's identity - so a fallback search has a plausible place to land.
MISMATCHES = [
    pytest.param({"amount": ODD_AMOUNT}, "paise", id="amount"),
    pytest.param({"currency": "USD"}, "USD", id="currency"),
    pytest.param({"notes": {"recoveros_payment_id": C}}, C, id="notes"),
]


@pytest.fixture
def spent(db_session, many):
    """
    Give B a prior recovery action with a real cost, so "no extra spend" is a
    comparison against something rather than against zero.
    """
    record = db_session.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.payment_id == B).one()
    log_audit(
        db_session, record,
        action="WHATSAPP_LINK_SENT",
        actor="system",
        details="Prior recovery action, so spend is non-zero before the mismatch.",
        cost_paise=50,
    )
    db_session.commit()
    assert spend_paise(db_session, record) == 50
    return record


@pytest.mark.parametrize("overrides,expected_in_reason", MISMATCHES)
@pytest.mark.asyncio
async def test_a_mismatch_is_refused_and_ledgered(
        db_session, many, spent, overrides, expected_in_reason):
    result = await settlement.handle_payment_link_paid(
        db_session, payload(PLINK_B, **overrides))

    assert result["status"] == "mismatch"
    assert result["payment_id"] == B
    assert expected_in_reason in result["reason"]

    # The refusal is a first-class outcome, not a silent return.
    held = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == HELD).one()
    assert held.payment_id == B
    assert held.actor == "system"
    assert held.cost_paise == 0
    assert "WHY_WE_DIDNT_ACT" in held.details
    assert PLINK_B in held.details
    assert expected_in_reason in held.details


@pytest.mark.parametrize("overrides,_reason", MISMATCHES)
@pytest.mark.asyncio
async def test_a_mismatch_changes_no_state(db_session, many, spent, overrides, _reason):
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B, **overrides))

    # No recovery, anywhere in the database.
    assert transitions(db_session) == 0
    assert state(db_session, B) == "INTERVENING"

    # The link is left unsettled so a corrected delivery can still land.
    link = link_of(db_session, PLINK_B)
    assert link.status == "created"
    assert link.razorpay_payment_id is None
    assert link.payment_id == B
    assert link.amount == many[B][1].amount


@pytest.mark.parametrize("overrides,_reason", MISMATCHES)
@pytest.mark.asyncio
async def test_a_mismatch_spends_nothing_extra(
        db_session, many, spent, overrides, _reason):
    before = spend_paise(db_session, spent)

    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B, **overrides))

    assert spend_paise(db_session, spent) == before == 50
    assert sum(e.cost_paise or 0 for e in db_session.query(AuditTrailEntry).all()) == 50


@pytest.mark.parametrize("overrides,_reason", MISMATCHES)
@pytest.mark.asyncio
async def test_a_mismatch_touches_no_other_record(
        db_session, many, spent, overrides, _reason):
    """
    The wrongness in each payload points at something real: D holds the odd
    amount, C holds the claimed identity. Neither may be drawn in.
    """
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B, **overrides))

    for other in (A, C, D):
        assert state(db_session, other) == "INTERVENING", other
        assert db_session.query(AuditTrailEntry).filter(
            AuditTrailEntry.payment_id == other).count() == 0, other

    for plink in (PLINK_A, PLINK_C, PLINK_D):
        link = link_of(db_session, plink)
        assert link.status == "created"
        assert link.razorpay_payment_id is None


@pytest.mark.parametrize("overrides,_reason", MISMATCHES)
@pytest.mark.asyncio
async def test_the_ledger_stays_valid_after_a_mismatch(
        db_session, many, spent, overrides, _reason):
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B, **overrides))

    result = ledger.verify_chain(db_session)

    assert result.valid is True, result.reason
    assert result.entries_checked == db_session.query(AuditTrailEntry).count()

    held = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == HELD).one()
    assert held.entry_hash
    assert held.prev_hash


# --- A hold is a pause, not a verdict ---------------------------------------


@pytest.mark.parametrize("overrides,_reason", MISMATCHES)
@pytest.mark.asyncio
async def test_a_corrected_delivery_still_settles_after_a_mismatch(
        db_session, many, spent, overrides, _reason):
    """
    The refusal must not poison the link. Razorpay redelivers, and a body that
    does add up has to be able to settle the record the first one could not.
    """
    await settlement.handle_payment_link_paid(db_session, payload(PLINK_B, **overrides))
    assert state(db_session, B) == "INTERVENING"

    result = await settlement.handle_payment_link_paid(db_session, payload(PLINK_B))

    assert result["status"] == "recovered"
    assert state(db_session, B) == "RECOVERED"
    assert transitions(db_session) == 1
    assert link_of(db_session, PLINK_B).status == "paid"

    # The refusal stays on the record as history; it is not rewritten away.
    assert db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == HELD).count() == 1
    assert ledger.verify_chain(db_session).valid is True

    # Still nobody else.
    for other in (A, C, D):
        assert state(db_session, other) == "INTERVENING"


@pytest.mark.asyncio
async def test_repeated_mismatches_accumulate_holds_and_recover_nothing(
        db_session, many, spent):
    """Three bad deliveries in a row leave three explanations and no recovery."""
    for overrides, _ in ((p.values[0], p.values[1]) for p in MISMATCHES):
        await settlement.handle_payment_link_paid(
            db_session, payload(PLINK_B, **overrides))

    assert db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == HELD).count() == 3
    assert transitions(db_session) == 0
    assert state(db_session, B) == "INTERVENING"
    assert link_of(db_session, PLINK_B).status == "created"
    assert sum(e.cost_paise or 0 for e in db_session.query(AuditTrailEntry).all()) == 50
    assert ledger.verify_chain(db_session).valid is True
