"""
The payer-facing GET landing after a Razorpay Payment Link.

The property worth defending here is negative. These query parameters arrive in
a URL the payer controls and can edit, so the landing page must never settle,
recover, or write anything. Settlement has its own authenticated path - the
signed payment_link.paid webhook checked against our own correlation row - and
this handler must not become a second, forgeable one.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.routes import webhooks

SECRET = "return-page-secret"
ORIGINAL = "pay_RETURN_ORIG01"
PLINK = "plink_RETURN_TEST1"
NEW_PAYMENT = "pay_RETURN_NEW001"
AMOUNT = 45000

# The exact query string Razorpay sent during the live Test Mode run.
LIVE_QUERY = (
    "?razorpay_payment_id=pay_TUPZ6oyBK5iHSG"
    "&razorpay_payment_link_id=plink_TUPWRjmzada94a"
    "&razorpay_payment_link_reference_id="
    "&razorpay_payment_link_status=paid"
    "&razorpay_signature=424af3c35621896c32b05e8db72636a6e97fa1d473e3b86d017d70a476feef9e"
)


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(webhooks, "DEMO_MODE", False)
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", SECRET)
    return TestClient(app)


@pytest.fixture
def intervening(db_session, payment_record):
    """A record mid-recovery, with the link that was created for it."""
    record = payment_record(
        payment_id=ORIGINAL, amount=AMOUNT, failure_class="AUTH_FRICTION",
        recovery_state="INTERVENING", recovery_channel="whatsapp_link",
    )
    db_session.add(record)
    db_session.commit()
    link = RazorpayPaymentLink(
        payment_id=ORIGINAL, recovery_action_id="c" * 64,
        razorpay_payment_link_id=PLINK, status="created",
        amount=AMOUNT, currency="INR",
    )
    db_session.add(link)
    db_session.commit()
    return record, link


# --- The redirect no longer 405s ------------------------------------------


def test_get_returns_a_page_instead_of_405(client):
    """This is the regression: Razorpay's redirect used to hit a POST-only route."""
    response = client.get("/api/webhooks/razorpay" + LIVE_QUERY)

    assert response.status_code == 200
    assert response.status_code != 405
    assert "text/html" in response.headers["content-type"]
    assert "Payment received" in response.text


def test_bare_get_without_parameters_is_fine(client):
    response = client.get("/api/webhooks/razorpay")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_unpaid_status_does_not_claim_success(client):
    response = client.get(
        "/api/webhooks/razorpay?razorpay_payment_link_status=cancelled")

    assert response.status_code == 200
    assert "Payment received" not in response.text
    assert "not completed" in response.text


# --- It must never settle --------------------------------------------------


def test_get_does_not_recover_the_record(client, db_session, intervening):
    record, link = intervening

    response = client.get(
        f"/api/webhooks/razorpay?razorpay_payment_link_id={PLINK}"
        f"&razorpay_payment_id={NEW_PAYMENT}&razorpay_payment_link_status=paid")

    assert response.status_code == 200
    assert record.recovery_state == "INTERVENING"
    assert link.status == "created"
    assert link.razorpay_payment_id is None


def test_get_writes_no_ledger_entry(client, db_session, intervening):
    before = db_session.query(AuditTrailEntry).count()

    client.get("/api/webhooks/razorpay" + LIVE_QUERY)

    assert db_session.query(AuditTrailEntry).count() == before


def test_a_forged_query_string_recovers_nothing(client, db_session, intervening):
    """
    The payer can edit this URL. Someone typing another payment's link id, or
    inventing one, must not be able to mark anything recovered.
    """
    record, link = intervening

    for forged in (
        f"?razorpay_payment_link_id={PLINK}&razorpay_payment_link_status=paid",
        "?razorpay_payment_link_id=plink_ATTACKER&razorpay_payment_link_status=paid",
        "?razorpay_payment_link_status=paid&razorpay_payment_id=pay_ANYTHING",
    ):
        assert client.get("/api/webhooks/razorpay" + forged).status_code == 200

    assert record.recovery_state == "INTERVENING"
    assert link.status == "created"
    assert db_session.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.recovery_state == "RECOVERED").count() == 0
    assert db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "STATE_INTERVENING_TO_RECOVERED").count() == 0


def test_query_values_are_escaped_into_the_page(client):
    response = client.get(
        "/api/webhooks/razorpay?razorpay_payment_link_id=%3Cscript%3Ealert(1)%3C/script%3E")

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


# --- POST behaviour unchanged ----------------------------------------------


def post(client, payload, secret=SECRET, signature=None):
    body = json.dumps(payload).encode()
    sig = signature if signature is not None else hmac.new(
        secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/webhooks/razorpay", content=body,
                       headers={"X-Razorpay-Signature": sig,
                                "Content-Type": "application/json"})


def link_paid_payload():
    return {"event": "payment_link.paid", "payload": {
        "payment_link": {"entity": {"id": PLINK, "status": "paid"}},
        "payment": {"entity": {"id": NEW_PAYMENT, "amount": AMOUNT, "currency": "INR"}}}}


def test_post_still_requires_a_valid_signature(client, db_session, intervening):
    record, _link = intervening

    assert post(client, link_paid_payload(), signature="forged").status_code == 401
    assert record.recovery_state == "INTERVENING"


def test_post_settlement_still_works_after_adding_the_get_route(client, db_session, intervening):
    record, link = intervening

    response = post(client, link_paid_payload())

    assert response.json()["result"]["status"] == "recovered"
    assert record.recovery_state == "RECOVERED"
    assert link.status == "paid"
    assert link.razorpay_payment_id == NEW_PAYMENT
    assert db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "STATE_INTERVENING_TO_RECOVERED").count() == 1


def test_get_after_settlement_changes_nothing(client, db_session, intervening):
    """The payer's browser lands after the webhook. It must stay a no-op."""
    record, link = intervening
    post(client, link_paid_payload())
    entries = db_session.query(AuditTrailEntry).count()

    client.get("/api/webhooks/razorpay" + LIVE_QUERY)

    assert record.recovery_state == "RECOVERED"
    assert db_session.query(AuditTrailEntry).count() == entries
    assert db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "STATE_INTERVENING_TO_RECOVERED").count() == 1
