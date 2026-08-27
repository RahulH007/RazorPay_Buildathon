"""
Priority 4: an opted-out contact gets no recovery, on the live webhook path.

Consent is already well covered in two places, and neither is this one:

  tests/test_consent.py    the registry itself - hashing, cross-payment
                           suppression, idempotency, the ledger entry.
  tests/test_policy.py     `decide_next_action` returning CONSENT_WITHDRAWN
                           when asked directly.

What has never been exercised is the whole path: a signed Razorpay
payment.failed for a contact who opted out earlier, arriving at a system with
live credentials loaded, going through classification and stopping at the
policy boundary with nothing sent and nothing spent.

The contact is the one seeded in app/tools/seed_guard_cases.py - Priya Menon,
+919812340004, opted out via `dtmf_9` on an earlier payment, with two later
payments (`pay_OPT01prior1` authentication_failed, `pay_OPT02prior2`
mandate_insufficient_funds) that must both be refused. Those payment ids and
reasons are reused here so the test and the seeded demo tell the same story.

Both reasons are in RULE_MAP, so this is a *known* reason being refused on
consent grounds - not the unmapped gate from Priority 3 doing the work. The
model is made unreachable file-wide to keep that distinction honest.

Isolation follows tests/test_live_flow_e2e.py: TestClient is never used as a
context manager, so the app lifespan never runs and the developer's
recoveros.db is untouched.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import consent, ledger, razorpay_client, recovery_actions
from app.classifier import RULE_MAP
from app.main import app
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.routes import webhooks

SECRET = "priority4-webhook-secret"

# Straight from app/tools/seed_guard_cases.py.
OPTED_OUT_PHONE = "+919812340004"
OPT_OUT_SOURCE = "dtmf_9"
PRIOR_PAYMENT = "pay_OPT00earlier0"
FIRST = "pay_OPT01prior1"
SECOND = "pay_OPT02prior2"

REFUSAL = "POLICY_DECLINED_CONSENT_WITHDRAWN"

CHANNEL_ACTIONS = (
    "WHATSAPP_LINK_SENT",
    "RETRY_SILENT_ATTEMPT",
    "MANDATE_RESEQUENCED",
    "VOICE_CALL_INITIATED",
)


class ModelWasConsulted(BaseException):
    """
    Not an Exception: `classifier.llm_classify` converts any Exception from the
    model into a HARD_DECLINE, which would disguise a rule-engine regression as
    a classification outcome. BaseException walks straight out through it.
    """


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(webhooks, "DEMO_MODE", False)
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", SECRET)
    return TestClient(app)


@pytest.fixture(autouse=True)
def live_gate_open_but_wired_to_explode(monkeypatch):
    """
    The harshest arrangement for this test: the live path reports itself open,
    so a consent leak would genuinely try to create a Payment Link - and that
    attempt raises instead of quietly succeeding.
    """
    def boom_link(source, payload):
        raise AssertionError(
            f"Payment Link creation attempted for an opted-out contact "
            f"(source={source!r})"
        )

    monkeypatch.setattr(razorpay_client, "create_payment_link", boom_link)
    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link", boom_link)
    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: source == LIVE_SOURCE)


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    """Every reason used here is in RULE_MAP; the model must stay unreachable."""
    import app.llm_agent as llm_agent

    async def boom(record):
        raise ModelWasConsulted(
            f"diagnose_failure was consulted for {record.error_reason!r}"
        )

    monkeypatch.setattr(llm_agent, "diagnose_failure", boom)


@pytest.fixture
def opted_out(db_session):
    """The contact withdrew consent on an earlier payment, via a voice DTMF 9."""
    consent.record_opt_out(db_session, OPTED_OUT_PHONE, OPT_OUT_SOURCE, PRIOR_PAYMENT)
    return OPTED_OUT_PHONE


def failed_payload(payment_id=FIRST, error_reason="authentication_failed",
                   amount=320000, phone=OPTED_OUT_PHONE, method="card"):
    return {
        "event": "payment.failed",
        "account_id": "acc_ConsentMerchant",
        "payload": {"payment": {"entity": {
            "id": payment_id, "amount": amount, "currency": "INR", "method": method,
            "email": "priya.menon@example.com", "contact": phone,
            "error_source": "customer", "error_step": "payment_authentication",
            "error_reason": error_reason,
            "error_description": "3DS challenge abandoned",
            "notes": {"customer_name": "Priya Menon"},
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


def entries(db, payment_id=None):
    q = db.query(AuditTrailEntry)
    if payment_id:
        q = q.filter(AuditTrailEntry.payment_id == payment_id)
    return q.order_by(AuditTrailEntry.sequence_no).all()


def actions(db, payment_id=None):
    return [e.action for e in entries(db, payment_id)]


# --- The refusal ------------------------------------------------------------


def test_a_known_reason_from_an_opted_out_contact_stops_at_failed_stopped(
        client, db_session, opted_out):
    assert "authentication_failed" in RULE_MAP

    assert post(client, failed_payload()).status_code == 200

    record = db_session.query(PaymentFailureRecord).one()
    assert record.source == LIVE_SOURCE
    assert record.recovery_state == "FAILED_STOPPED"

    # Classification still ran, by the rule engine, before consent stopped it.
    classified = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "CLASSIFIED_AUTH_FRICTION").one()
    assert classified.actor == "rule_engine"
    assert record.failure_class == "AUTH_FRICTION"

    recorded = actions(db_session, FIRST)
    required = ["RECORD_INGESTED", "CLASSIFIED_AUTH_FRICTION",
                "STATE_INGESTED_TO_DIAGNOSED", REFUSAL,
                "STATE_DIAGNOSED_TO_FAILED_STOPPED"]
    positions = [recorded.index(a) for a in required]
    assert positions == sorted(positions), recorded


def test_the_refusal_is_ledgered_with_its_reason(client, db_session, opted_out):
    post(client, failed_payload())

    refusal = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == REFUSAL).one()

    assert refusal.actor == "policy_engine"
    assert refusal.cost_paise == 0
    assert "WHY_WE_DIDNT_ACT" in refusal.details
    assert "CONSENT_WITHDRAWN" in refusal.details
    # It names how and when consent was withdrawn, not merely that it was.
    assert OPT_OUT_SOURCE in refusal.details
    assert PRIOR_PAYMENT in refusal.details

    stopped = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "STATE_DIAGNOSED_TO_FAILED_STOPPED").one()
    assert stopped.actor == "policy_engine"


def test_nothing_was_sent_created_or_spent(client, db_session, opted_out):
    post(client, failed_payload())

    recorded = actions(db_session)
    for action in CHANNEL_ACTIONS:
        assert action not in recorded

    # Policy refused before the action was ever entered, so the in-action
    # consent guard never had to fire.
    assert "SUPPRESSED_CONSENT" not in recorded
    assert "STATE_DIAGNOSED_TO_INTERVENING" not in recorded

    assert db_session.query(RazorpayPaymentLink).count() == 0
    assert sum(e.cost_paise or 0 for e in entries(db_session)) == 0


# --- Suppression is a property of the contact, not the payment --------------


def test_suppression_persists_across_payments(client, db_session, opted_out):
    """
    The load-bearing property. A per-payment flag would refuse the first and
    let the second through - which is how a contact who opted out gets messaged
    again a week later.
    """
    post(client, failed_payload(FIRST, "authentication_failed", 320000))
    post(client, failed_payload(SECOND, "mandate_insufficient_funds", 145000,
                                method="upi"))

    assert "mandate_insufficient_funds" in RULE_MAP
    assert db_session.query(PaymentFailureRecord).count() == 2

    for payment_id in (FIRST, SECOND):
        record = db_session.query(PaymentFailureRecord).filter(
            PaymentFailureRecord.payment_id == payment_id).one()
        assert record.recovery_state == "FAILED_STOPPED", payment_id
        assert actions(db_session, payment_id).count(REFUSAL) == 1, payment_id

    # A different failure class, a different channel, the same silence.
    assert db_session.query(RazorpayPaymentLink).count() == 0
    assert sum(e.cost_paise or 0 for e in entries(db_session)) == 0


def test_the_same_webhook_recovers_when_the_contact_never_opted_out(
        client, db_session, monkeypatch):
    """
    The control for every assertion above.

    Without it, "the record stopped" proves only that *something* stopped it -
    the exploding link seam, the unreachable model, a typo in the payload. This
    is the identical webhook with the `opted_out` fixture withheld, and it must
    run all the way to a sent message. The live seam is closed here so the demo
    path is taken and nothing tries to reach Razorpay.
    """
    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: False)

    post(client, failed_payload())

    record = db_session.query(PaymentFailureRecord).one()
    recorded = actions(db_session, FIRST)

    assert REFUSAL not in recorded
    assert "WHATSAPP_LINK_SENT" in recorded
    assert record.recovery_state == "INTERVENING"


def test_a_duplicate_webhook_is_a_no_op(client, db_session, opted_out):
    post(client, failed_payload())
    after_first = len(entries(db_session))

    post(client, failed_payload())
    post(client, failed_payload())

    assert db_session.query(PaymentFailureRecord).count() == 1
    assert len(entries(db_session)) == after_first
    assert actions(db_session).count(REFUSAL) == 1
    assert actions(db_session).count("RECORD_INGESTED") == 1


# --- The synthetic pipeline -------------------------------------------------


@pytest.mark.asyncio
async def test_the_synthetic_pipeline_is_unaffected(db_session, payment_record):
    """A seeded record from a contact who never opted out behaves as before."""
    record = payment_record(
        payment_id="pay_synth_consent_ok", customer_phone="+919812340099",
        error_reason="authentication_failed", failure_class="AUTH_FRICTION",
        recovery_state="INTERVENING", source=SYNTHETIC_SOURCE,
    )
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(db_session, record)

    assert result["action"] == "whatsapp_link"
    assert result["link_url"].startswith("https://rzp.io/i/demo_")
    assert db_session.query(RazorpayPaymentLink).count() == 0
    assert "WHATSAPP_LINK_SENT" in actions(db_session, record.payment_id)


@pytest.mark.asyncio
async def test_consent_is_scoped_to_the_contact_not_to_the_source(
        db_session, payment_record, opted_out):
    """
    The mirror image of the test above, and the correct behaviour: the same
    opted-out contact appearing in the synthetic batch is silenced there too.
    Consent belongs to the person, not to the pipeline that found them.
    """
    record = payment_record(
        payment_id="pay_synth_consent_off", customer_phone=OPTED_OUT_PHONE,
        error_reason="authentication_failed", failure_class="AUTH_FRICTION",
        recovery_state="INTERVENING", source=SYNTHETIC_SOURCE,
    )
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(db_session, record)

    assert result["action"] == "suppressed"
    assert result["customer_contacted"] is False
    recorded = actions(db_session, record.payment_id)
    assert "SUPPRESSED_CONSENT" in recorded
    assert "WHATSAPP_LINK_SENT" not in recorded


# --- Ledger -----------------------------------------------------------------


def test_the_ledger_stays_valid_across_a_refused_flow(client, db_session, opted_out):
    post(client, failed_payload(FIRST, "authentication_failed", 320000))
    post(client, failed_payload(SECOND, "mandate_insufficient_funds", 145000,
                                method="upi"))
    post(client, failed_payload(FIRST, "authentication_failed", 320000))  # redelivery

    result = ledger.verify_chain(db_session)

    assert result.valid is True, result.reason
    assert result.entries_checked == db_session.query(AuditTrailEntry).count()

    # The opt-out itself is on the chain, ahead of both refusals.
    withdrawn = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "CONSENT_WITHDRAWN").one()
    assert withdrawn.actor == "customer"
    refusals = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == REFUSAL).all()
    assert len(refusals) == 2
    assert all(r.sequence_no > withdrawn.sequence_no for r in refusals)
