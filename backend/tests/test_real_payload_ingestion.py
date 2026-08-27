"""
Priority 1: real Razorpay payment.failed ingestion.

What the rest of the suite already proves is that the *pipeline* works. What it
does not prove is that it works on the body Razorpay actually sends. Every
payment.failed fixture elsewhere in these tests is a hand-trimmed object holding
only the eleven fields the normalizer reads. A real webhook carries the full
payment entity - `status`, `order_id`, `acquirer_data`, `card_id`, nulls in
place of absent values - plus the event envelope (`entity`, `contains`,
`created_at`) around it.

So this file posts the verbatim Razorpay payment.failed shape, signed, through
the real HTTP route, and pins the real-world quirks a trimmed fixture cannot
reach:

  * `notes` arrives as an empty *list*, not an empty object, when the payment
    carried no notes;
  * `error_reason`, `contact`, `invoice_id`, `currency` and `method` can be null
    rather than absent.

Isolation follows tests/test_live_flow_e2e.py exactly: TestClient is never used
as a context manager, so the app lifespan never runs and the developer's
recoveros.db is untouched; the route is bound to the in-memory session; conftest
blocks the Razorpay client and pins llm_cache to replay.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import copy
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.routes import webhooks

SECRET = "priority1-webhook-secret"
HELD = "UNMAPPED_REASON_HELD_FOR_REVIEW"

# The Razorpay payment.failed webhook body, field for field. Nothing is pruned:
# the keys this system ignores are present precisely so the test proves they are
# ignored safely rather than assumed absent.
REAL_PAYMENT_FAILED = {
    "entity": "event",
    "account_id": "acc_BFQ7uQEaa7j2z7",
    "event": "payment.failed",
    "contains": ["payment"],
    "payload": {
        "payment": {
            "entity": {
                "id": "pay_H9oR0gLCaVlV6m",
                "entity": "payment",
                "amount": 100000,
                "currency": "INR",
                "status": "failed",
                "order_id": "order_H9o382Wbafhmin",
                "invoice_id": None,
                "international": False,
                "method": "card",
                "amount_refunded": 0,
                "refund_status": None,
                "captured": False,
                "description": "Test Transaction",
                "card_id": "card_H9oR0hLCaVlV6n",
                "bank": None,
                "wallet": None,
                "vpa": None,
                "email": "gaurav.kumar@example.com",
                "contact": "+919000090000",
                "notes": [],
                "fee": None,
                "tax": None,
                "error_code": "BAD_REQUEST_ERROR",
                "error_description": "Payment processing failed because of an "
                                     "error at bank or wallet gateway.",
                "error_source": "gateway",
                "error_step": "payment_authentication",
                "error_reason": "payment_failed",
                "acquirer_data": {"auth_code": None},
                "created_at": 1620210964,
            }
        }
    },
    "created_at": 1620210964,
}


def real_payload(**entity_overrides):
    payload = copy.deepcopy(REAL_PAYMENT_FAILED)
    payload["payload"]["payment"]["entity"].update(entity_overrides)
    return payload


@pytest.fixture
def client(db_session, monkeypatch):
    """The route bound to the isolated session, with real signature checking."""
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(webhooks, "DEMO_MODE", False)
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", SECRET)
    return TestClient(app)


@pytest.fixture(autouse=True)
def no_live_link(monkeypatch):
    """Keep the Payment Link seam shut; ingestion is what is under test here."""
    from app import recovery_actions

    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: False)


@pytest.fixture
def stub_diagnosis(monkeypatch):
    """
    A deterministic diagnosis, so an assertion about ingestion never depends on
    a model response. `payment_failed` is not in RULE_MAP, so the live payload
    takes the slow path.
    """
    async def stub(record):
        from app.schemas import FailureDiagnosis
        return FailureDiagnosis(
            root_cause_class="AUTH_FRICTION",
            technical_explanation="Issuer declined the authentication.",
            suggested_action="Ask the customer to retry.",
            confidence=0.9,
        ), {"model": "gemini-3.6-flash", "latency_ms": 1,
            "input_tokens": 1, "output_tokens": 1, "confidence": 0.9}

    import app.llm_agent as llm_agent
    monkeypatch.setattr(llm_agent, "diagnose_failure", stub)


def post(client, payload, secret=SECRET):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )


def actions(db):
    return [e.action for e in db.query(AuditTrailEntry).all()]


# --- The real body, ingested --------------------------------------------------


def test_real_payment_failed_body_is_ingested(client, db_session, stub_diagnosis):
    """The full Razorpay event, signed, end to end through the HTTP route."""
    response = post(client, REAL_PAYMENT_FAILED)

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "event": "payment.failed",
        "payment_id": "pay_H9oR0gLCaVlV6m",
    }

    record = db_session.query(PaymentFailureRecord).one()
    assert record.payment_id == "pay_H9oR0gLCaVlV6m"
    assert record.amount == 100000
    assert record.currency == "INR"
    assert record.method == "card"
    # account_id, not a value invented locally.
    assert record.merchant_id == "acc_BFQ7uQEaa7j2z7"
    assert record.customer_email == "gaurav.kumar@example.com"
    assert record.customer_phone == "+919000090000"
    assert record.error_reason == "payment_failed"
    assert record.error_source == "gateway"
    assert record.error_step == "payment_authentication"
    assert record.error_description.startswith("Payment processing failed")
    assert record.source == "razorpay_webhook"

    # Ingested exactly once, and the ledger says so.
    recorded = actions(db_session)
    assert recorded.count("RECORD_INGESTED") == 1
    assert recorded[0] == "RECORD_INGESTED"
    assert any(a.startswith("CLASSIFIED_") for a in recorded)


def test_empty_notes_arrives_as_a_list_and_does_not_break_ingestion(
        client, db_session, stub_diagnosis):
    """
    Razorpay serialises absent notes as `[]`, not `{}`. A `.get()` on that would
    raise inside a background task and lose the event silently.
    """
    assert REAL_PAYMENT_FAILED["payload"]["payment"]["entity"]["notes"] == []

    post(client, REAL_PAYMENT_FAILED)

    record = db_session.query(PaymentFailureRecord).one()
    # No name to be had, and none invented.
    assert record.customer_name == "Razorpay Customer"


def test_a_customer_name_in_notes_is_used_when_present(client, db_session, stub_diagnosis):
    post(client, real_payload(notes={"customer_name": "Gaurav Kumar"}))

    assert db_session.query(PaymentFailureRecord).one().customer_name == "Gaurav Kumar"


@pytest.mark.parametrize("overrides,field,expected", [
    ({"error_reason": None}, "error_reason", "unknown"),
    ({"contact": None}, "customer_phone", ""),
    ({"invoice_id": None}, "invoice_id", None),
    ({"currency": None}, "currency", "INR"),
    ({"method": None}, "method", "unknown"),
])
def test_nulls_in_the_real_entity_map_to_safe_values(
        client, db_session, stub_diagnosis, overrides, field, expected):
    """Real payloads carry nulls where a trimmed fixture simply omits the key."""
    response = post(client, real_payload(**overrides))

    assert response.status_code == 200
    record = db_session.query(PaymentFailureRecord).one()
    assert getattr(record, field) == expected


def test_the_real_body_is_ingested_exactly_once_on_redelivery(
        client, db_session, stub_diagnosis):
    """Razorpay redelivers the identical body; ingestion is keyed on payment id."""
    post(client, REAL_PAYMENT_FAILED)
    entries = db_session.query(AuditTrailEntry).count()

    second = post(client, REAL_PAYMENT_FAILED)

    assert second.status_code == 200
    assert db_session.query(PaymentFailureRecord).count() == 1
    assert db_session.query(AuditTrailEntry).count() == entries
    assert actions(db_session).count("RECORD_INGESTED") == 1


def test_an_unsigned_real_body_is_rejected_and_ingests_nothing(client, db_session):
    """The body being genuine is not the claim; the signature is."""
    body = json.dumps(REAL_PAYMENT_FAILED).encode()

    response = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": "not-the-digest",
                 "Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert db_session.query(PaymentFailureRecord).count() == 0
    assert db_session.query(AuditTrailEntry).count() == 0


def test_ingestion_alone_reaches_no_payment_link(client, db_session, stub_diagnosis):
    """
    `payment_failed` is not in RULE_MAP, so the live gate holds the record for
    review: ingested and classified, nothing spent, nothing sent.
    """
    post(client, REAL_PAYMENT_FAILED)

    recorded = actions(db_session)
    assert HELD in recorded
    assert "WHATSAPP_LINK_SENT" not in recorded
    assert db_session.query(RazorpayPaymentLink).count() == 0
    assert sum(e.cost_paise or 0 for e in db_session.query(AuditTrailEntry).all()) == 0
