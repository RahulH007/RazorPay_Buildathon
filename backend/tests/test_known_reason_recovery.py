"""
Priority 2: a RULE_MAP-recognized live reason drives one automatic recovery.

The chain under test, end to end and in one place:

    signed payment.failed
      -> source=razorpay_webhook
      -> rule_engine classification (no model consulted)
      -> policy approval
      -> exactly one WHATSAPP_LINK_SENT, through the Razorpay client gate
      -> INTERVENING

Most links in that chain already have coverage somewhere. Two do not, and they
are the two that would fail silently:

  * Nothing asserts the classification actor on the live path. If
    `authentication_failed` stopped matching RULE_MAP and fell through to the
    model, the class would still come back AUTH_FRICTION and every existing
    assertion in the suite would still pass. Here `diagnose_failure` is replaced
    with something that raises, so the fast path is proven by the model never
    being reachable.

  * Nothing asserts that policy *approved* on the live path - only that a link
    appeared. A decline that still somehow produced a send would go unnoticed.

Isolation follows tests/test_live_flow_e2e.py: TestClient is never used as a
context manager, so the app lifespan never runs and the developer's
recoveros.db is untouched; the route is bound to the in-memory session; conftest
blocks the real Razorpay client and pins llm_cache to replay.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import ledger, recovery_actions
from app.config import CHANNEL_COSTS_PAISE
from app.guardrails import cac_ceiling_paise, spend_paise
from app.main import app
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.routes import webhooks

SECRET = "priority2-webhook-secret"
PAYMENT_ID = "pay_KnownReason001"
PLINK = "plink_KnownReason01"
AMOUNT = 450000
KNOWN_REASON = "authentication_failed"


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(webhooks, "DEMO_MODE", False)
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", SECRET)
    return TestClient(app)


class ModelWasConsulted(BaseException):
    """
    Deliberately not an Exception.

    `classifier.llm_classify` wraps the model call in `except Exception` and
    converts any failure into a HARD_DECLINE plus an ESCALATED_TO_HUMAN entry -
    correct in production, but it would swallow an ordinary assertion here and
    leave the regression looking like a classification outcome. Inheriting from
    BaseException walks straight out through that handler.
    """


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    """
    The model is unreachable for the whole file.

    `authentication_failed` is in RULE_MAP, so the fast path must answer without
    it. If the rule lookup ever regresses, the run stops here instead of quietly
    returning a plausible class from the slow path.
    """
    import app.llm_agent as llm_agent

    async def boom(record):
        raise ModelWasConsulted(
            f"diagnose_failure was consulted for {record.error_reason!r}, "
            f"which the rule engine is supposed to answer without a model."
        )

    monkeypatch.setattr(llm_agent, "diagnose_failure", boom)


@pytest.fixture
def link_calls(monkeypatch):
    """
    The one seam through which a Payment Link may be created.

    conftest already makes `get_client` raise, so any path that tries to reach
    Razorpay another way fails loudly rather than being counted here.
    """
    calls = []

    def fake_create(source, payload):
        calls.append({"source": source, "payload": payload})
        return {"id": PLINK, "short_url": "https://rzp.io/i/known01"}

    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: source == LIVE_SOURCE)
    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link",
                        fake_create)
    # Pinned so this file does not depend on the developer's PUBLIC_BASE_URL:
    # live creation refuses a loopback callback, and config defaults to one.
    monkeypatch.setattr(recovery_actions, "PAYMENT_LINK_CALLBACK_URL", "https://tests.recoveros.example/api/webhooks/razorpay")
    return calls


def failed_payload(error_reason=KNOWN_REASON, payment_id=PAYMENT_ID, amount=AMOUNT):
    return {
        "event": "payment.failed",
        "account_id": "acc_KnownMerchant",
        "payload": {"payment": {"entity": {
            "id": payment_id, "amount": amount, "currency": "INR", "method": "card",
            "email": "known@example.com", "contact": "+919876500777",
            "error_source": "bank", "error_step": "payment_authorization",
            "error_reason": error_reason,
            "error_description": "Your payment didn't go through as the OTP was not entered.",
            "notes": {"customer_name": "Known Reason Customer"},
        }}},
    }


def post(client, payload, secret=SECRET):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )


def entries(db):
    return db.query(AuditTrailEntry).order_by(AuditTrailEntry.sequence_no).all()


def actions(db):
    return [e.action for e in entries(db)]


# --- Classification: the fast path, by the rule engine ----------------------


def test_a_known_reason_is_classified_by_the_rule_engine(client, db_session, link_calls):
    """AUTH_FRICTION, decided deterministically, with no model consulted."""
    assert post(client, failed_payload()).status_code == 200

    record = db_session.query(PaymentFailureRecord).one()
    assert record.source == LIVE_SOURCE
    assert record.failure_class == "AUTH_FRICTION"
    assert record.recovery_channel == "whatsapp_link"

    classified = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "CLASSIFIED_AUTH_FRICTION").one()
    assert classified.actor == "rule_engine"
    assert KNOWN_REASON in classified.details

    # The slow path left no trace, because it never ran.
    recorded = actions(db_session)
    assert "FAILURE_DIAGNOSED_LLM" not in recorded
    assert "ESCALATED_TO_HUMAN" not in recorded
    # And the live gate did not hold it: this reason is approved for automation.
    assert "UNMAPPED_REASON_HELD_FOR_REVIEW" not in recorded


# --- Policy: approval, not merely an absence of refusal ---------------------


def test_policy_approves_and_owns_the_transition_to_intervening(
        client, db_session, link_calls):
    post(client, failed_payload())

    record = db_session.query(PaymentFailureRecord).one()
    assert record.recovery_state == "INTERVENING"

    recorded = actions(db_session)
    assert not any(a.startswith("POLICY_DECLINED_") for a in recorded)

    moved = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "STATE_DIAGNOSED_TO_INTERVENING").one()
    assert moved.actor == "policy_engine"
    # The approval names the channel and the attempt it authorised.
    assert "whatsapp_link" in moved.details
    assert "Attempt 1 of 2" in moved.details


def test_the_spend_is_ledgered_and_inside_the_cac_ceiling(client, db_session, link_calls):
    post(client, failed_payload())

    record = db_session.query(PaymentFailureRecord).one()
    sent = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "WHATSAPP_LINK_SENT").one()

    assert sent.cost_paise == CHANNEL_COSTS_PAISE["AUTH_FRICTION"]
    assert spend_paise(db_session, record) == sent.cost_paise
    assert spend_paise(db_session, record) <= cac_ceiling_paise(record)


# --- Exactly one action, through the gate -----------------------------------


def test_exactly_one_recovery_action_through_the_razorpay_gate(
        client, db_session, link_calls):
    post(client, failed_payload())

    recorded = actions(db_session)
    assert recorded.count("WHATSAPP_LINK_SENT") == 1
    # No other channel fired alongside it.
    assert "RETRY_SILENT_ATTEMPT" not in recorded
    assert "MANDATE_RESEQUENCED" not in recorded
    assert "VOICE_CALL_INITIATED" not in recorded
    assert "SUPPRESSED_CONSENT" not in recorded

    # The link was created once, through the one permitted seam, carrying the
    # correlation note settlement will later look for.
    assert len(link_calls) == 1
    call = link_calls[0]
    assert call["source"] == LIVE_SOURCE
    assert call["payload"]["amount"] == AMOUNT
    assert call["payload"]["currency"] == "INR"
    assert call["payload"]["notes"] == {"recoveros_payment_id": PAYMENT_ID}

    link = db_session.query(RazorpayPaymentLink).one()
    assert link.payment_id == PAYMENT_ID
    assert link.razorpay_payment_link_id == PLINK
    assert link.status == "created"
    sent = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "WHATSAPP_LINK_SENT").one()
    assert link.recovery_action_id == sent.entry_hash


def test_the_chain_runs_in_order(client, db_session, link_calls):
    """Ingest, classify, move, act - in that order and nothing before ingest."""
    post(client, failed_payload())

    recorded = actions(db_session)
    required = [
        "RECORD_INGESTED",
        "CLASSIFIED_AUTH_FRICTION",
        "STATE_INGESTED_TO_DIAGNOSED",
        "STATE_DIAGNOSED_TO_INTERVENING",
        "WHATSAPP_LINK_SENT",
    ]
    positions = [recorded.index(a) for a in required]
    assert positions == sorted(positions), recorded
    assert recorded[0] == "RECORD_INGESTED"


# --- Redelivery ------------------------------------------------------------


def test_redelivery_repeats_no_action(client, db_session, link_calls):
    """Razorpay retries the same body; the customer must not be messaged twice."""
    post(client, failed_payload())
    after_first = len(entries(db_session))

    post(client, failed_payload())
    post(client, failed_payload())

    assert db_session.query(PaymentFailureRecord).count() == 1
    assert len(entries(db_session)) == after_first
    assert actions(db_session).count("WHATSAPP_LINK_SENT") == 1
    assert len(link_calls) == 1
    assert db_session.query(RazorpayPaymentLink).count() == 1


# --- Synthetic records stay off the network --------------------------------


@pytest.mark.asyncio
async def test_a_synthetic_record_with_the_same_reason_cannot_reach_razorpay(
        db_session, payment_record, link_calls):
    """
    Same failure class, same channel, same live credentials - and still no API
    call, because the record does not carry the live source.
    """
    record = payment_record(
        payment_id="pay_synth_known", error_reason=KNOWN_REASON,
        failure_class="AUTH_FRICTION", recovery_state="INTERVENING",
        source=SYNTHETIC_SOURCE,
    )
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(db_session, record)

    assert link_calls == []
    assert result["link_url"].startswith("https://rzp.io/i/demo_")
    assert db_session.query(RazorpayPaymentLink).count() == 0


# --- Ledger ----------------------------------------------------------------


def test_the_ledger_is_complete_and_valid_for_this_flow(client, db_session, link_calls):
    post(client, failed_payload())
    post(client, failed_payload())  # redelivery, adds nothing

    result = ledger.verify_chain(db_session)

    assert result.valid is True, result.reason
    assert result.entries_checked == db_session.query(AuditTrailEntry).count()

    # Every entry belongs to this payment, and every one is hash-linked.
    for entry in entries(db_session):
        assert entry.payment_id == PAYMENT_ID
        assert entry.entry_hash
        assert entry.actor
