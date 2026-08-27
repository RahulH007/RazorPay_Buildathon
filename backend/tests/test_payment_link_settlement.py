"""
Step 2: Payment Link settlement and correlation.

The property most of these tests defend is negative: a payment must never
recover a record it does not belong to. The Payment Link row this system wrote
is the trust anchor; webhook contents are evidence, checked against it.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest

from app import settlement
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink

ORIGINAL = "pay_ORIGINAL_0001"
PLINK = "plink_TEST000001"
NEW_PAYMENT = "pay_NEW_0000789"
AMOUNT = 450000


@pytest.fixture
def settled_setup(db_session, payment_record):
    """An original failure being chased, and the link created for it."""
    record = payment_record(
        payment_id=ORIGINAL,
        amount=AMOUNT,
        failure_class="AUTH_FRICTION",
        recovery_state="INTERVENING",
        recovery_channel="whatsapp_link",
    )
    db_session.add(record)
    db_session.commit()

    link = RazorpayPaymentLink(
        payment_id=ORIGINAL,
        recovery_action_id="a" * 64,
        razorpay_payment_link_id=PLINK,
        status="created",
        amount=AMOUNT,
        currency="INR",
    )
    db_session.add(link)
    db_session.commit()
    return record, link


def link_paid_payload(link_id=PLINK, payment_id=NEW_PAYMENT, amount=AMOUNT,
                      currency="INR", notes=None):
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


def recovery_transitions(db):
    return db.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "STATE_INTERVENING_TO_RECOVERED"
    ).count()


# --- A / 19. The happy path -------------------------------------------------


@pytest.mark.asyncio
async def test_payment_link_paid_recovers_the_original_record(db_session, settled_setup):
    record, link = settled_setup

    result = await settlement.handle_payment_link_paid(
        db_session, link_paid_payload(notes={"recoveros_payment_id": ORIGINAL}))

    assert result["status"] == "recovered"
    assert record.recovery_state == "RECOVERED"
    assert link.status == "paid"
    assert link.razorpay_payment_id == NEW_PAYMENT
    assert recovery_transitions(db_session) == 1

    # The correlation must be legible in the ledger, not just in the database.
    entry = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "STATE_INTERVENING_TO_RECOVERED").one()
    assert PLINK in entry.details
    assert NEW_PAYMENT in entry.details


@pytest.mark.asyncio
async def test_immutable_correlation_fields_are_untouched(db_session, settled_setup):
    _record, link = settled_setup
    before = (link.payment_id, link.razorpay_payment_link_id,
              link.recovery_action_id, link.amount)

    await settlement.handle_payment_link_paid(db_session, link_paid_payload())

    assert (link.payment_id, link.razorpay_payment_link_id,
            link.recovery_action_id, link.amount) == before


# --- 20. Unknown link (security) -------------------------------------------


@pytest.mark.asyncio
async def test_unknown_payment_link_recovers_nothing(db_session, settled_setup):
    """A link this system never created must not settle anything."""
    record, link = settled_setup

    result = await settlement.handle_payment_link_paid(
        db_session, link_paid_payload(link_id="plink_ATTACKER"))

    assert result["status"] == "not_found"
    assert record.recovery_state == "INTERVENING"
    assert link.status == "created"
    assert recovery_transitions(db_session) == 0


@pytest.mark.asyncio
async def test_payload_without_a_link_id_is_rejected(db_session, settled_setup):
    result = await settlement.handle_payment_link_paid(
        db_session, {"event": "payment_link.paid", "payload": {}})

    assert result["status"] == "rejected"
    assert recovery_transitions(db_session) == 0


# --- 21 / 22 / 23. Validation ----------------------------------------------


@pytest.mark.asyncio
async def test_amount_mismatch_does_not_recover(db_session, settled_setup):
    record, link = settled_setup

    result = await settlement.handle_payment_link_paid(
        db_session, link_paid_payload(amount=90000))

    assert result["status"] == "mismatch"
    assert record.recovery_state == "INTERVENING"
    assert link.status == "created"
    assert link.razorpay_payment_id is None
    assert recovery_transitions(db_session) == 0
    assert db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "SETTLEMENT_MISMATCH_HELD").count() == 1


@pytest.mark.asyncio
async def test_currency_mismatch_does_not_recover(db_session, settled_setup):
    record, link = settled_setup

    result = await settlement.handle_payment_link_paid(
        db_session, link_paid_payload(currency="USD"))

    assert result["status"] == "mismatch"
    assert record.recovery_state == "INTERVENING"
    assert link.status == "created"
    assert recovery_transitions(db_session) == 0


@pytest.mark.asyncio
async def test_conflicting_notes_do_not_recover(db_session, settled_setup):
    """Notes disagreeing with our own row is disqualifying, not overridable."""
    record, link = settled_setup

    result = await settlement.handle_payment_link_paid(
        db_session, link_paid_payload(notes={"recoveros_payment_id": "pay_SOMEONE_ELSE"}))

    assert result["status"] == "mismatch"
    assert "pay_SOMEONE_ELSE" in result["reason"]
    assert record.recovery_state == "INTERVENING"
    assert link.status == "created"
    assert recovery_transitions(db_session) == 0


# --- 24. Notes absent -------------------------------------------------------


@pytest.mark.asyncio
async def test_absent_notes_still_settle(db_session, settled_setup):
    """
    Notes are defence in depth. Real payloads omit them inconsistently across
    event types, so absence must not block a settlement the link id and amount
    already prove.
    """
    record, link = settled_setup

    result = await settlement.handle_payment_link_paid(db_session, link_paid_payload())

    assert result["status"] == "recovered"
    assert record.recovery_state == "RECOVERED"
    assert link.status == "paid"


# --- 25. Duplicate delivery -------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_payment_link_paid_is_a_no_op(db_session, settled_setup):
    record, link = settled_setup
    payload = link_paid_payload()

    first = await settlement.handle_payment_link_paid(db_session, payload)
    entries_after_first = db_session.query(AuditTrailEntry).count()

    second = await settlement.handle_payment_link_paid(db_session, payload)

    assert first["status"] == "recovered"
    assert second["status"] == "already_recovered"
    assert recovery_transitions(db_session) == 1
    assert db_session.query(AuditTrailEntry).count() == entries_after_first
    assert record.recovery_state == "RECOVERED"


# --- 17. payment.captured direct match regression --------------------------


@pytest.mark.asyncio
async def test_payment_captured_direct_match_still_works(db_session, payment_record):
    record = payment_record(payment_id="pay_direct_1", recovery_state="INTERVENING")
    db_session.add(record)
    db_session.commit()

    result = await settlement.handle_payment_captured(db_session, "pay_direct_1")

    assert result["status"] == "recovered"
    assert record.recovery_state == "RECOVERED"


# --- 18. payment.captured with a new id and no link id ---------------------


@pytest.mark.asyncio
async def test_captured_new_payment_without_link_id_does_not_guess(db_session, settled_setup):
    """
    The dangerous heuristic this test forbids: correlating a captured payment
    to a link by amount or recency. One customer's payment would recover
    another customer's record.
    """
    record, link = settled_setup

    payload = {"event": "payment.captured",
               "payload": {"payment": {"entity": {"id": NEW_PAYMENT, "amount": AMOUNT}}}}
    result = await settlement.handle_payment_captured(db_session, NEW_PAYMENT, payload)

    assert result["status"] == "not_found"
    assert record.recovery_state == "INTERVENING"
    assert link.status == "created"
    assert recovery_transitions(db_session) == 0


@pytest.mark.asyncio
async def test_captured_with_an_explicit_link_id_does_correlate(db_session, settled_setup):
    """When Razorpay does supply the link id, the same core settles it."""
    record, link = settled_setup

    payload = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": NEW_PAYMENT, "amount": AMOUNT, "currency": "INR",
        "payment_link_id": PLINK,
    }}}}
    result = await settlement.handle_payment_captured(db_session, NEW_PAYMENT, payload)

    assert result["status"] == "recovered"
    assert record.recovery_state == "RECOVERED"
    assert link.razorpay_payment_id == NEW_PAYMENT


# --- 26. Event order --------------------------------------------------------


@pytest.mark.asyncio
async def test_link_paid_then_captured_settles_once(db_session, settled_setup):
    record, link = settled_setup

    await settlement.handle_payment_link_paid(db_session, link_paid_payload())
    entries = db_session.query(AuditTrailEntry).count()

    captured = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": NEW_PAYMENT, "amount": AMOUNT, "currency": "INR",
        "payment_link_id": PLINK,
    }}}}
    result = await settlement.handle_payment_captured(db_session, NEW_PAYMENT, captured)

    assert result["status"] == "already_recovered"
    assert recovery_transitions(db_session) == 1
    assert db_session.query(AuditTrailEntry).count() == entries


@pytest.mark.asyncio
async def test_captured_then_link_paid_settles_once(db_session, settled_setup):
    record, link = settled_setup

    captured = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": NEW_PAYMENT, "amount": AMOUNT, "currency": "INR",
        "payment_link_id": PLINK,
    }}}}
    await settlement.handle_payment_captured(db_session, NEW_PAYMENT, captured)
    entries = db_session.query(AuditTrailEntry).count()

    result = await settlement.handle_payment_link_paid(db_session, link_paid_payload())

    assert result["status"] == "already_recovered"
    assert recovery_transitions(db_session) == 1
    assert db_session.query(AuditTrailEntry).count() == entries


# --- 15. Metrics ------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_settlement_does_not_double_count(db_session, settled_setup):
    from app.routes.metrics import get_dashboard_metrics  # noqa: F401

    record, _link = settled_setup
    payload = link_paid_payload()

    await settlement.handle_payment_link_paid(db_session, payload)
    await settlement.handle_payment_link_paid(db_session, payload)

    recovered = db_session.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.recovery_state == "RECOVERED").all()
    assert len(recovered) == 1
    assert sum(r.amount for r in recovered) == AMOUNT


# --- 27. payment.authorized -------------------------------------------------


@pytest.mark.asyncio
async def test_payment_authorized_is_ignored_by_the_route(db_session, settled_setup, monkeypatch):
    """
    Authorisation is not capture. Driven through the real dispatch rather than
    asserting a handler is absent, so adding one later would fail this test.
    """
    from app.routes import webhooks

    record, link = settled_setup
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(webhooks, "DEMO_MODE", True)
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", "XXXXXXXXXXXXXXXXXXXXXX")

    payload = {"event": "payment.authorized", "payload": {"payment": {"entity": {
        "id": NEW_PAYMENT, "amount": AMOUNT, "payment_link_id": PLINK,
    }}}}

    class FakeRequest:
        async def body(self):
            import json
            return json.dumps(payload).encode()

        async def json(self):
            return payload

        headers = {}

    class FakeBackgroundTasks:
        def add_task(self, *a, **kw):
            raise AssertionError("payment.authorized must not schedule work")

    result = await webhooks.receive_webhook(FakeRequest(), FakeBackgroundTasks())

    assert result["status"] == "ignored"
    assert record.recovery_state == "INTERVENING"
    assert link.status == "created"
    assert recovery_transitions(db_session) == 0


@pytest.mark.asyncio
async def test_payment_link_paid_dispatches_through_the_route(db_session, settled_setup, monkeypatch):
    from app.routes import webhooks

    record, _link = settled_setup
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(webhooks, "DEMO_MODE", True)
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", "XXXXXXXXXXXXXXXXXXXXXX")

    payload = link_paid_payload()

    class FakeRequest:
        async def body(self):
            import json
            return json.dumps(payload).encode()

        async def json(self):
            return payload

        headers = {}

    class FakeBackgroundTasks:
        def add_task(self, *a, **kw):
            pass

    result = await webhooks.receive_webhook(FakeRequest(), FakeBackgroundTasks())

    assert result["event"] == "payment_link.paid"
    assert result["result"]["status"] == "recovered"
    assert record.recovery_state == "RECOVERED"


# --- Malformed input --------------------------------------------------------


@pytest.mark.parametrize("payload", [None, {}, "nonsense", {"payload": None},
                                     {"payload": {"payment_link": None}}])
@pytest.mark.asyncio
async def test_malformed_payloads_do_not_crash_or_recover(db_session, settled_setup, payload):
    record, link = settled_setup

    result = await settlement.handle_payment_link_paid(db_session, payload)

    assert result["status"] in ("rejected", "not_found")
    assert record.recovery_state == "INTERVENING"
    assert recovery_transitions(db_session) == 0
