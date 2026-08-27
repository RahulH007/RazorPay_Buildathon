"""
Priority 3: an unknown live reason is held, not acted on.

RULE_MAP is the set of error codes a human has approved for automatic recovery.
Razorpay's live vocabulary is wider - `payment_failed` and `payment_cancelled`
both arrive from real Test Mode traffic and neither is in it. Classification
still runs, so the record stays visible and diagnosable; only the automatic
action is withheld.

What the suite already proves is the gate's behaviour on trimmed fixtures
(tests/test_event_adapter.py, at the ingest_and_process level) and through the
HTTP route (tests/test_live_flow_e2e.py). This file adds the three things
neither reaches:

  * the *real* Razorpay entity shape - full payment entity, event envelope,
    `notes: []`, nulls - driven at both reasons, rather than an 11-field object;
  * proof that the policy engine itself is never consulted, not merely that
    execute_recovery is skipped;
  * `ledger.verify_chain` over a held flow. Every existing verify_chain call
    walks a ledger built from *mapped* reasons; the entry the gate writes has
    never been checked for hash linkage.

The diagnosis is stubbed throughout. The property under test is the safety
boundary, and an assertion about it must not depend on what a model returns on
the day it runs.

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

from app import event_adapter, ledger, razorpay_client, recovery_actions
from app.classifier import RULE_MAP
from app.main import app
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.routes import webhooks

# The verbatim Razorpay payment.failed body, shared with Priority 1 so there is
# one definition of "what Razorpay actually sends" rather than two that drift.
from test_real_payload_ingestion import real_payload

SECRET = "priority3-webhook-secret"
HELD = "UNMAPPED_REASON_HELD_FOR_REVIEW"

# Both unmapped reasons, with the error_source/error_step Razorpay pairs them
# with in real Test Mode traffic.
UNMAPPED_REASONS = [
    pytest.param(
        {"error_reason": "payment_failed",
         "error_source": "gateway",
         "error_step": "payment_authorization",
         "error_description": "Payment failed"},
        id="payment_failed",
    ),
    pytest.param(
        {"error_reason": "payment_cancelled",
         "error_source": "customer",
         "error_step": "payment_authentication",
         "error_description": "Your payment has been cancelled. Try again or "
                              "complete the payment later."},
        id="payment_cancelled",
    ),
]


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(webhooks, "DEMO_MODE", False)
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", SECRET)
    return TestClient(app)


@pytest.fixture(autouse=True)
def never_calls_razorpay(monkeypatch):
    """
    Independent of DEMO_MODE. If the gate leaks these raise rather than quietly
    no-op, so a leak fails loudly instead of passing.
    """
    def boom_link(source, payload):
        raise AssertionError(f"Payment Link creation attempted (source={source!r})")

    monkeypatch.setattr(razorpay_client, "create_payment_link", boom_link)
    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link", boom_link)
    # A held record must not even ask whether the live path is open.
    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: True)


@pytest.fixture(autouse=True)
def stub_diagnosis(monkeypatch):
    """Deterministic diagnosis: this file tests the gate, not the model."""
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


def entries(db):
    return db.query(AuditTrailEntry).order_by(AuditTrailEntry.sequence_no).all()


def actions(db):
    return [e.action for e in entries(db)]


# --- The gate, on the real payload shape, at both reasons -------------------


@pytest.mark.parametrize("overrides", UNMAPPED_REASONS)
def test_an_unknown_reason_is_ingested_classified_and_held(client, db_session, overrides):
    reason = overrides["error_reason"]
    assert reason not in RULE_MAP

    response = post(client, real_payload(**overrides))
    assert response.status_code == 200

    record = db_session.query(PaymentFailureRecord).one()
    assert record.source == LIVE_SOURCE
    assert record.error_reason == reason
    assert record.error_source == overrides["error_source"]

    # Classification still ran - the record is visible and diagnosable.
    assert record.failure_class == "AUTH_FRICTION"
    recorded = actions(db_session)
    assert len([a for a in recorded if a.startswith("CLASSIFIED_")]) == 1

    # And it stopped there.
    assert record.recovery_state == "DIAGNOSED"
    assert recorded.count(HELD) == 1
    assert recorded.count("RECORD_INGESTED") == 1


@pytest.mark.parametrize("overrides", UNMAPPED_REASONS)
def test_nothing_was_decided_spent_or_sent(client, db_session, overrides):
    post(client, real_payload(**overrides))

    recorded = actions(db_session)

    # No policy outcome of any kind, in either direction.
    assert not any(a.startswith("POLICY_DECLINED_") for a in recorded)
    assert "STATE_DIAGNOSED_TO_INTERVENING" not in recorded

    # No channel fired.
    assert "WHATSAPP_LINK_SENT" not in recorded
    assert "RETRY_SILENT_ATTEMPT" not in recorded
    assert "MANDATE_RESEQUENCED" not in recorded
    assert "VOICE_CALL_INITIATED" not in recorded

    # No Razorpay artefact, no money.
    assert db_session.query(RazorpayPaymentLink).count() == 0
    assert sum(e.cost_paise or 0 for e in entries(db_session)) == 0


def _policy_spy(monkeypatch):
    """
    Record every consultation of the policy engine.

    `decide_next_action` is imported into recovery_actions' namespace, so the
    spy goes there rather than on app.policy. Recording happens before the
    raise on purpose: the webhook route runs ingestion in a background task
    wrapped in `except Exception`, so a raise alone would be swallowed and the
    guard would pass while proving nothing. The list is what fails the test.
    """
    calls = []

    def spy(db, record, **kwargs):
        calls.append(record.payment_id)
        raise AssertionError("policy was consulted for an unmapped reason")

    monkeypatch.setattr(recovery_actions, "decide_next_action", spy)
    return calls


@pytest.mark.parametrize("overrides", UNMAPPED_REASONS)
def test_the_policy_engine_is_never_consulted(client, db_session, overrides, monkeypatch):
    """
    Stronger than "no action was taken": the decision is never even asked for.

    execute_recovery is deliberately left real here. Stubbing it would make the
    policy spy unreachable and the assertion vacuous - a leak has to be able to
    travel all the way to the decision for its absence to mean anything.
    """
    policy_calls = _policy_spy(monkeypatch)

    post(client, real_payload(**overrides))

    assert policy_calls == []
    assert db_session.query(PaymentFailureRecord).one().recovery_state == "DIAGNOSED"


def test_the_policy_spy_bites_on_a_mapped_reason(client, db_session, monkeypatch):
    """
    The control for the test above. `authentication_failed` is in RULE_MAP, so
    the gate does not hold it and policy *must* be consulted - which is what
    makes `policy_calls == []` a real assertion rather than a vacuous one.
    """
    policy_calls = _policy_spy(monkeypatch)

    post(client, real_payload(error_reason="authentication_failed"))

    assert policy_calls == ["pay_H9oR0gLCaVlV6m"]


# --- Redelivery ------------------------------------------------------------


@pytest.mark.parametrize("overrides", UNMAPPED_REASONS)
def test_a_duplicate_webhook_is_a_true_no_op(client, db_session, overrides):
    payload = real_payload(**overrides)

    post(client, payload)
    after_first = len(entries(db_session))

    post(client, payload)
    post(client, payload)

    assert db_session.query(PaymentFailureRecord).count() == 1
    assert len(entries(db_session)) == after_first
    recorded = actions(db_session)
    assert recorded.count(HELD) == 1
    assert recorded.count("RECORD_INGESTED") == 1
    assert len([a for a in recorded if a.startswith("CLASSIFIED_")]) == 1


# --- The synthetic pipeline is untouched -----------------------------------


@pytest.mark.parametrize("overrides", UNMAPPED_REASONS)
@pytest.mark.asyncio
async def test_a_synthetic_record_with_the_same_reason_is_not_held(
        db_session, payment_record, overrides):
    """
    The gate keys on source. A seeded record carrying the identical reason
    classifies and proceeds exactly as it did before the gate existed.
    """
    from app.classifier import classify

    record = payment_record(
        payment_id=f"pay_synth_{overrides['error_reason']}",
        error_reason=overrides["error_reason"],
        error_description=overrides["error_description"],
        source=SYNTHETIC_SOURCE,
    )
    db_session.add(record)
    db_session.commit()

    await classify(db_session, record)

    recorded = [e.action for e in db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.payment_id == record.payment_id).all()]

    assert HELD not in recorded
    assert record.failure_class == "AUTH_FRICTION"
    assert record.recovery_state == "DIAGNOSED"


# --- Ledger ----------------------------------------------------------------


@pytest.mark.parametrize("overrides", UNMAPPED_REASONS)
def test_the_ledger_stays_valid_across_a_held_flow(client, db_session, overrides):
    """
    Every other verify_chain in the suite walks a ledger built from mapped
    reasons. The entry the gate writes has never been checked for linkage.
    """
    post(client, real_payload(**overrides))
    post(client, real_payload(**overrides))  # redelivery

    result = ledger.verify_chain(db_session)

    assert result.valid is True, result.reason
    assert result.entries_checked == db_session.query(AuditTrailEntry).count()

    held = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == HELD).one()
    assert held.actor == "system"
    assert held.cost_paise == 0
    assert held.entry_hash
    assert held.prev_hash
