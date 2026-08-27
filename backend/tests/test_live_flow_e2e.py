"""
Step 4: end-to-end regression across Steps 1-3, driven through the real HTTP
route with FastAPI's TestClient.

Two isolation rules this file must never break:

  The developer's recoveros.db is not touched. TestClient is deliberately NOT
  used as a context manager, because the app's lifespan runs create_all,
  installs triggers and verifies the chain against the real DATABASE_URL. Every
  test here binds the route to the in-memory session from conftest instead.

  No external API is reached. conftest blocks the Razorpay client and pins
  llm_cache to replay; this file additionally asserts the Payment Link seam is
  only called where it should be.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import ledger
from app.main import app
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.routes import webhooks

SECRET = "step4-webhook-secret"
ORIGINAL = "pay_E2E_ORIGINAL01"
PLINK = "plink_E2E_TEST01"
NEW_PAYMENT = "pay_E2E_NEW00001"
AMOUNT = 450000
HELD = "UNMAPPED_REASON_HELD_FOR_REVIEW"


@pytest.fixture
def client(db_session, monkeypatch):
    """
    The route, bound to the isolated test session, with real signature checking.

    DEMO_MODE is false here on purpose: this exercises the fail-closed path and
    proves the suite is safe in the configuration that would otherwise reach
    live Razorpay.
    """
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(webhooks, "DEMO_MODE", False)
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", SECRET)
    # No `with`: skipping lifespan keeps recoveros.db untouched.
    return TestClient(app)


@pytest.fixture
def live_link_created(monkeypatch):
    """Make the live Payment Link path active, with the API call mocked."""
    from app import recovery_actions

    calls = []

    def fake_create(source, payload):
        calls.append({"source": source, "payload": payload})
        return {"id": PLINK, "short_url": "https://rzp.io/i/e2e01"}

    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: source == "razorpay_webhook")
    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link", fake_create)
    # Pinned so these tests do not depend on the developer's PUBLIC_BASE_URL.
    # Live link creation now refuses a loopback callback, and config defaults to
    # localhost, so an unset environment would otherwise block every test here.
    monkeypatch.setattr(recovery_actions, "PAYMENT_LINK_CALLBACK_URL", "https://tests.recoveros.example/api/webhooks/razorpay")
    return calls


def post(client, payload, secret=SECRET, signature=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    sig = signature if signature is not None else hmac.new(
        secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )


def failed_payload(error_reason="authentication_failed", payment_id=ORIGINAL,
                   amount=AMOUNT):
    return {
        "event": "payment.failed",
        "account_id": "acc_E2EMerchant",
        "payload": {"payment": {"entity": {
            "id": payment_id, "amount": amount, "currency": "INR", "method": "card",
            "email": "e2e@example.com", "contact": "+919876500777",
            "error_source": "bank", "error_step": "payment_authorization",
            "error_reason": error_reason,
            "error_description": "Your payment didn't go through as it was declined by the bank.",
            "notes": {"customer_name": "E2E Customer"},
        }}},
    }


def link_paid_payload(link_id=PLINK, amount=AMOUNT, currency="INR", notes=None,
                      new_payment_id=NEW_PAYMENT):
    entity = {"id": new_payment_id, "amount": amount, "currency": currency}
    if notes is not None:
        entity["notes"] = notes
    return {
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": {"id": link_id, "status": "paid"}},
                    "payment": {"entity": entity}},
    }


def actions(db):
    return [e.action for e in db.query(AuditTrailEntry).all()]


def transitions(db):
    return sum(1 for a in actions(db) if a == "STATE_INTERVENING_TO_RECOVERED")


# --- 2. payment.failed -> recovery ------------------------------------------


def test_payment_failed_drives_a_full_recovery(client, db_session, live_link_created):
    response = post(client, failed_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

    record = db_session.query(PaymentFailureRecord).one()
    assert record.source == "razorpay_webhook"
    assert record.failure_class == "AUTH_FRICTION"
    assert record.recovery_state == "INTERVENING"

    link = db_session.query(RazorpayPaymentLink).one()
    assert link.payment_id == ORIGINAL
    assert link.razorpay_payment_link_id == PLINK
    assert link.status == "created"
    assert link.amount == AMOUNT
    assert link.currency == "INR"
    assert link.razorpay_payment_id is None
    assert len(link.recovery_action_id) == 64

    # The correlation points at the real ledger entry for the action.
    sent = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "WHATSAPP_LINK_SENT").one()
    assert link.recovery_action_id == sent.entry_hash

    # The live payload was used, not the demo placeholder.
    assert len(live_link_created) == 1
    call = live_link_created[0]
    assert call["source"] == "razorpay_webhook"
    assert call["payload"]["notes"] == {"recoveros_payment_id": ORIGINAL}
    assert call["payload"]["amount"] == AMOUNT
    assert call["payload"]["currency"] == "INR"


# --- 3. Settlement to RECOVERED ---------------------------------------------


def test_payment_link_paid_completes_the_loop(client, db_session, live_link_created):
    post(client, failed_payload())
    response = post(client, link_paid_payload())

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "recovered"

    record = db_session.query(PaymentFailureRecord).one()
    link = db_session.query(RazorpayPaymentLink).one()

    assert record.recovery_state == "RECOVERED"
    assert link.status == "paid"
    assert link.razorpay_payment_id == NEW_PAYMENT

    recorded = actions(db_session)
    assert "STATE_INGESTED_TO_DIAGNOSED" in recorded
    assert "STATE_DIAGNOSED_TO_INTERVENING" in recorded
    assert transitions(db_session) == 1

    assert ledger.verify_chain(db_session).valid is True


# --- 4. Delivery ordering ---------------------------------------------------


def test_order_link_paid_then_captured(client, db_session, live_link_created):
    post(client, failed_payload())
    post(client, link_paid_payload())
    entries = db_session.query(AuditTrailEntry).count()

    captured = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": NEW_PAYMENT, "amount": AMOUNT, "currency": "INR",
        "payment_link_id": PLINK}}}}
    response = post(client, captured)

    assert response.json()["result"]["status"] == "already_recovered"
    assert transitions(db_session) == 1
    assert db_session.query(AuditTrailEntry).count() == entries


def test_order_captured_then_link_paid(client, db_session, live_link_created):
    post(client, failed_payload())

    captured = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": NEW_PAYMENT, "amount": AMOUNT, "currency": "INR",
        "payment_link_id": PLINK}}}}
    post(client, captured)
    entries = db_session.query(AuditTrailEntry).count()

    response = post(client, link_paid_payload())

    assert response.json()["result"]["status"] == "already_recovered"
    assert transitions(db_session) == 1
    assert db_session.query(AuditTrailEntry).count() == entries


# --- 5. Duplicate delivery --------------------------------------------------


def test_duplicate_payment_failed_and_duplicate_settlement(client, db_session, live_link_created):
    post(client, failed_payload())
    entries_after_first = db_session.query(AuditTrailEntry).count()

    post(client, failed_payload())

    assert db_session.query(PaymentFailureRecord).count() == 1
    assert db_session.query(AuditTrailEntry).count() == entries_after_first
    recorded = actions(db_session)
    assert recorded.count("RECORD_INGESTED") == 1
    assert len([a for a in recorded if a.startswith("CLASSIFIED_")]) == 1
    assert recorded.count("WHATSAPP_LINK_SENT") == 1
    assert len(live_link_created) == 1

    post(client, link_paid_payload())
    after_settlement = db_session.query(AuditTrailEntry).count()

    response = post(client, link_paid_payload())

    assert response.json()["result"]["status"] == "already_recovered"
    assert transitions(db_session) == 1
    assert db_session.query(AuditTrailEntry).count() == after_settlement


# --- 6 / 7. Unmapped live reasons -------------------------------------------


@pytest.mark.parametrize("error_reason", ["payment_failed", "payment_cancelled"])
def test_unmapped_live_reason_is_held(client, db_session, live_link_created,
                                      monkeypatch, error_reason):
    async def stub_diagnose(record):
        from app.schemas import FailureDiagnosis
        return FailureDiagnosis(
            root_cause_class="AUTH_FRICTION", technical_explanation="Issuer declined.",
            suggested_action="Ask the customer to retry.", confidence=0.9,
        ), {"model": "gemini-3.6-flash", "latency_ms": 1,
            "input_tokens": 1, "output_tokens": 1, "confidence": 0.9}

    import app.llm_agent as llm_agent
    monkeypatch.setattr(llm_agent, "diagnose_failure", stub_diagnose)

    post(client, failed_payload(error_reason=error_reason))

    record = db_session.query(PaymentFailureRecord).one()
    recorded = actions(db_session)

    assert record.recovery_state == "DIAGNOSED"
    assert recorded.count(HELD) == 1
    assert "WHATSAPP_LINK_SENT" not in recorded
    assert "STATE_DIAGNOSED_TO_INTERVENING" not in recorded
    assert not any(a.startswith("POLICY_DECLINED_") for a in recorded)
    assert db_session.query(RazorpayPaymentLink).count() == 0
    assert live_link_created == []
    assert sum(e.cost_paise or 0 for e in db_session.query(AuditTrailEntry).all()) == 0

    # Redelivery adds nothing.
    entries = db_session.query(AuditTrailEntry).count()
    post(client, failed_payload(error_reason=error_reason))
    assert db_session.query(AuditTrailEntry).count() == entries
    assert actions(db_session).count(HELD) == 1


# --- 8. Malformed and unsigned webhooks -------------------------------------


@pytest.mark.parametrize("payload", [
    {},
    {"event": "payment.failed"},
    {"event": "payment.failed", "payload": {}},
    {"event": "payment.failed", "payload": {"payment": {"entity": {}}}},
    {"event": "payment.failed", "account_id": "acc_1",
     "payload": {"payment": {"entity": {"amount": 100}}}},
])
def test_malformed_payment_failed_is_rejected(client, db_session, live_link_created, payload):
    response = post(client, payload)

    assert response.status_code in (200, 400)
    if response.status_code == 200:
        # No event, or an event with no handler: safely ignored.
        assert response.json()["status"] == "ignored"
    assert db_session.query(PaymentFailureRecord).count() == 0
    assert db_session.query(AuditTrailEntry).count() == 0
    assert live_link_created == []


def test_invalid_json_body_does_not_create_anything(client, db_session):
    response = post(client, None, raw=b"{not json")

    assert response.status_code >= 400
    assert db_session.query(PaymentFailureRecord).count() == 0
    assert db_session.query(AuditTrailEntry).count() == 0


def test_invalid_signature_is_rejected(client, db_session, live_link_created):
    response = post(client, failed_payload(), signature="deadbeef")

    assert response.status_code == 401
    assert db_session.query(PaymentFailureRecord).count() == 0
    assert live_link_created == []


def test_missing_signature_is_rejected_in_real_mode(client, db_session):
    response = post(client, failed_payload(), signature="")

    assert response.status_code == 401
    assert db_session.query(PaymentFailureRecord).count() == 0


def test_placeholder_secret_is_rejected_in_real_mode(client, db_session, monkeypatch):
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", "XXXXXXXXXXXXXXXXXXXXXX")

    response = post(client, failed_payload(), secret="XXXXXXXXXXXXXXXXXXXXXX")

    assert response.status_code == 401
    assert db_session.query(PaymentFailureRecord).count() == 0


# --- 9. Dispatch matrix -----------------------------------------------------


def test_unknown_and_authorized_events_are_ignored(client, db_session, live_link_created):
    for event in ("payment.authorized", "subscription.charged", "refund.created"):
        response = post(client, {"event": event, "payload": {"payment": {"entity": {
            "id": "pay_x", "amount": AMOUNT, "payment_link_id": PLINK}}}})
        assert response.json()["status"] == "ignored", event

    assert db_session.query(PaymentFailureRecord).count() == 0
    assert db_session.query(AuditTrailEntry).count() == 0
    assert live_link_created == []


def test_invoice_paid_still_routes_to_its_handler(client, db_session, payment_record):
    record = payment_record(payment_id="pay_inv_1", invoice_id="inv_E2E_1",
                            recovery_state="INTERVENING")
    db_session.add(record)
    db_session.commit()

    response = post(client, {"event": "invoice.paid", "payload": {
        "invoice": {"entity": {"id": "inv_E2E_1"}}}})

    assert response.json()["result"]["status"] == "recovered"
    assert record.recovery_state == "RECOVERED"


# --- 10. Payment Link security ----------------------------------------------


def test_unknown_link_recovers_nothing(client, db_session, live_link_created):
    post(client, failed_payload())

    response = post(client, link_paid_payload(link_id="plink_ATTACKER"))

    assert response.json()["result"]["status"] == "not_found"
    assert db_session.query(PaymentFailureRecord).one().recovery_state == "INTERVENING"
    assert db_session.query(RazorpayPaymentLink).one().status == "created"
    assert transitions(db_session) == 0
    assert "SETTLEMENT_MISMATCH_HELD" not in actions(db_session)


@pytest.mark.parametrize("kwargs", [
    {"amount": 90000},
    {"currency": "USD"},
    {"notes": {"recoveros_payment_id": "pay_SOMEONE_ELSE"}},
])
def test_settlement_mismatches_are_held(client, db_session, live_link_created, kwargs):
    post(client, failed_payload())

    response = post(client, link_paid_payload(**kwargs))

    assert response.json()["result"]["status"] == "mismatch"
    assert db_session.query(PaymentFailureRecord).one().recovery_state == "INTERVENING"
    link = db_session.query(RazorpayPaymentLink).one()
    assert link.status == "created"
    assert link.razorpay_payment_id is None
    assert transitions(db_session) == 0
    assert actions(db_session).count("SETTLEMENT_MISMATCH_HELD") == 1


# --- 11. No guessing --------------------------------------------------------


def test_captured_matching_only_on_amount_recovers_nothing(client, db_session, live_link_created):
    """
    A captured payment with the right amount, right currency and no link id
    must not settle. Correlating on resemblance would let one customer's
    payment recover another customer's record.
    """
    post(client, failed_payload())

    response = post(client, {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": NEW_PAYMENT, "amount": AMOUNT, "currency": "INR"}}}})

    assert response.json()["result"]["status"] == "not_found"
    assert db_session.query(PaymentFailureRecord).one().recovery_state == "INTERVENING"
    assert db_session.query(RazorpayPaymentLink).one().status == "created"
    assert transitions(db_session) == 0


# --- 12. Metrics exactly once ----------------------------------------------


def test_metrics_count_the_recovery_exactly_once(client, db_session, live_link_created):
    post(client, failed_payload())

    def recovered():
        rows = db_session.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.recovery_state == "RECOVERED").all()
        return len(rows), sum(r.amount for r in rows)

    assert recovered() == (0, 0)

    post(client, link_paid_payload())
    assert recovered() == (1, AMOUNT)

    post(client, link_paid_payload())
    post(client, link_paid_payload())
    assert recovered() == (1, AMOUNT)


# --- 13. Ledger integrity ---------------------------------------------------


def test_ledger_stays_valid_across_every_flow(client, db_session, live_link_created):
    post(client, failed_payload())
    post(client, link_paid_payload(amount=90000))          # mismatch
    post(client, link_paid_payload(link_id="plink_NOPE"))  # unknown
    post(client, link_paid_payload())                      # settles
    post(client, link_paid_payload())                      # duplicate
    post(client, {"event": "payment.authorized", "payload": {}})

    result = ledger.verify_chain(db_session)

    assert result.valid is True, result.reason
    assert result.entries_checked == db_session.query(AuditTrailEntry).count()
    assert transitions(db_session) == 1
