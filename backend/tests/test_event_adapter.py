"""
Step 3: the unmapped-reason safety gate on the live webhook path.

The property under test is a boundary, not a classifier-quality fix. RULE_MAP
is the set of error codes a human approved for automatic recovery. Razorpay's
live vocabulary is wider than the seeded dataset's, and a code nobody has ruled
on must not cause this system to spend money and message a stranger - however
good the diagnosis happens to be.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import json

import pytest

from app import event_adapter, razorpay_client, recovery_actions
from app.classifier import RULE_MAP
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink

HELD = "UNMAPPED_REASON_HELD_FOR_REVIEW"


@pytest.fixture(autouse=True)
def never_calls_razorpay(monkeypatch):
    """
    Independent of DEMO_MODE. If the gate leaks, these raise rather than
    silently no-op, so a leak fails loudly instead of passing quietly.
    """
    def boom_client(source):
        raise AssertionError(f"Razorpay client built (source={source!r})")

    def boom_link(source, payload):
        raise AssertionError(f"Payment Link creation attempted (source={source!r})")

    monkeypatch.setattr(razorpay_client, "get_client", boom_client)
    monkeypatch.setattr(razorpay_client, "create_payment_link", boom_link)
    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link", boom_link)


def failed_payload(error_reason, error_description="Something went wrong.",
                   payment_id="pay_LiveGate00001", amount=450000):
    return {
        "event": "payment.failed",
        "account_id": "acc_LiveMerchant01",
        "payload": {"payment": {"entity": {
            "id": payment_id,
            "amount": amount,
            "currency": "INR",
            "method": "card",
            "email": "customer@example.com",
            "contact": "+919876500123",
            "error_source": "bank",
            "error_step": "payment_authorization",
            "error_reason": error_reason,
            "error_description": error_description,
            "notes": {"customer_name": "Live Customer"},
        }}},
    }


async def ingest(db, payload):
    normalized = event_adapter.normalize_razorpay_payment_failed(payload)
    assert normalized is not None
    return await event_adapter.ingest_and_process(db, normalized)


def actions(db, payment_id=None):
    q = db.query(AuditTrailEntry)
    if payment_id:
        q = q.filter(AuditTrailEntry.payment_id == payment_id)
    return [e.action for e in q.all()]


# --- 1 / 2 / 14. Mapped reasons must still auto-recover ---------------------


@pytest.mark.parametrize("error_reason,expected_class", [
    ("authentication_failed", "AUTH_FRICTION"),
    ("bank_technical_error", "TRANSIENT_TECHNICAL"),
])
@pytest.mark.asyncio
async def test_mapped_reasons_still_auto_recover(db_session, error_reason, expected_class):
    """Proves the gate is not accidentally class-wide."""
    assert error_reason in RULE_MAP

    result = await ingest(db_session, failed_payload(error_reason))

    record = db_session.query(PaymentFailureRecord).one()
    assert result["status"] == "ingested"
    assert record.failure_class == expected_class
    assert record.recovery_state != "DIAGNOSED"  # recovery ran

    recorded = actions(db_session)
    assert HELD not in recorded
    # Policy actually executed on this path.
    assert any(a.startswith("STATE_DIAGNOSED_TO_") for a in recorded)


# --- 3 / 4 / 10 / 11. Unmapped reasons are held -----------------------------


@pytest.mark.parametrize("error_reason,description", [
    ("payment_failed",
     "Your payment didn't go through as it was declined by the bank. Try again."),
    ("payment_cancelled",
     "Your payment was cancelled. Please retry the payment."),
])
@pytest.mark.asyncio
async def test_unmapped_live_reasons_are_held(db_session, error_reason, description, monkeypatch):
    assert error_reason not in RULE_MAP

    # Keep the assertion on the safety property, not on a model response: give
    # classification a deterministic answer so the record lands DIAGNOSED
    # rather than escalating on an unavailable diagnosis.
    async def stub_diagnose(record):
        from app.schemas import FailureDiagnosis
        return FailureDiagnosis(
            root_cause_class="AUTH_FRICTION",
            technical_explanation="Issuer declined the authorisation.",
            suggested_action="Ask the customer to retry with another card.",
            confidence=0.9,
        ), {"model": "gemini-3.6-flash", "latency_ms": 100,
            "input_tokens": 10, "output_tokens": 5, "confidence": 0.9}

    import app.llm_agent as llm_agent
    monkeypatch.setattr(llm_agent, "diagnose_failure", stub_diagnose)

    result = await ingest(db_session, failed_payload(error_reason, description))

    record = db_session.query(PaymentFailureRecord).one()
    recorded = actions(db_session)

    assert result["status"] == "held_for_review"
    assert record.source == "razorpay_webhook"
    assert record.recovery_state == "DIAGNOSED"

    # Classification happened; the record is visible and diagnosable.
    assert any(a.startswith("CLASSIFIED_") for a in recorded)
    assert HELD in recorded

    # But nothing was decided, spent or sent.
    assert db_session.query(RazorpayPaymentLink).count() == 0
    assert "WHATSAPP_LINK_SENT" not in recorded
    assert not any(a.startswith("POLICY_DECLINED_") for a in recorded)
    assert "RETRY_SILENT_ATTEMPT" not in recorded
    assert "MANDATE_RESEQUENCED" not in recorded
    assert "VOICE_CALL_INITIATED" not in recorded
    assert "STATE_DIAGNOSED_TO_INTERVENING" not in recorded
    assert sum(e.cost_paise or 0 for e in db_session.query(AuditTrailEntry).all()) == 0


@pytest.mark.asyncio
async def test_held_entry_explains_itself(db_session, monkeypatch):
    async def stub_diagnose(record):
        from app.schemas import FailureDiagnosis
        return FailureDiagnosis(
            root_cause_class="AUTH_FRICTION", technical_explanation="x",
            suggested_action="y", confidence=0.9,
        ), {"model": "gemini-3.6-flash", "latency_ms": 1,
            "input_tokens": 1, "output_tokens": 1, "confidence": 0.9}

    import app.llm_agent as llm_agent
    monkeypatch.setattr(llm_agent, "diagnose_failure", stub_diagnose)

    await ingest(db_session, failed_payload("payment_failed"))

    entry = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == HELD).one()

    assert entry.actor == "system"
    assert entry.cost_paise == 0
    assert "payment_failed" in entry.details
    assert "RULE_MAP" in entry.details
    assert "WHY_WE_DIDNT_ACT" in entry.details


# --- 6 / 7. No policy, no API call -----------------------------------------


@pytest.mark.asyncio
async def test_execute_recovery_is_never_called_for_an_unmapped_reason(db_session, monkeypatch):
    """The gate must prevent the call, not merely make it harmless."""
    called = []

    async def spy(*args, **kwargs):
        called.append(kwargs.get("source"))
        return {}

    monkeypatch.setattr(event_adapter, "execute_recovery", spy)

    await ingest(db_session, failed_payload("payment_cancelled"))

    assert called == []


@pytest.mark.asyncio
async def test_execute_recovery_is_still_called_for_a_mapped_reason(db_session, monkeypatch):
    called = []

    async def spy(*args, **kwargs):
        called.append(kwargs.get("source"))
        return {}

    monkeypatch.setattr(event_adapter, "execute_recovery", spy)

    await ingest(db_session, failed_payload("authentication_failed"))

    assert called == ["razorpay_webhook"]


# --- 9 / 13. Duplicate unmapped webhook ------------------------------------


@pytest.mark.asyncio
async def test_duplicate_unmapped_webhook_is_idempotent(db_session, monkeypatch):
    async def stub_diagnose(record):
        from app.schemas import FailureDiagnosis
        return FailureDiagnosis(
            root_cause_class="AUTH_FRICTION", technical_explanation="x",
            suggested_action="y", confidence=0.9,
        ), {"model": "gemini-3.6-flash", "latency_ms": 1,
            "input_tokens": 1, "output_tokens": 1, "confidence": 0.9}

    import app.llm_agent as llm_agent
    monkeypatch.setattr(llm_agent, "diagnose_failure", stub_diagnose)

    payload = failed_payload("payment_failed")

    first = await ingest(db_session, payload)
    entries_after_first = db_session.query(AuditTrailEntry).count()

    second = await ingest(db_session, payload)

    assert first["status"] == "held_for_review"
    assert second["status"] == "duplicate"
    assert db_session.query(PaymentFailureRecord).count() == 1
    assert db_session.query(AuditTrailEntry).count() == entries_after_first

    recorded = actions(db_session)
    assert recorded.count("RECORD_INGESTED") == 1
    assert recorded.count(HELD) == 1
    assert len([a for a in recorded if a.startswith("CLASSIFIED_")]) == 1


# --- 16. Source controls the behaviour --------------------------------------


@pytest.mark.asyncio
async def test_the_gate_is_scoped_to_live_records(db_session, monkeypatch):
    """
    A synthetic record with the same unmapped reason must not be held - the
    gate keys on source, and the simulator's path is untouched.
    """
    async def stub_diagnose(record):
        from app.schemas import FailureDiagnosis
        return FailureDiagnosis(
            root_cause_class="AUTH_FRICTION", technical_explanation="x",
            suggested_action="y", confidence=0.9,
        ), {"model": "gemini-3.6-flash", "latency_ms": 1,
            "input_tokens": 1, "output_tokens": 1, "confidence": 0.9}

    import app.llm_agent as llm_agent
    from app.classifier import classify
    monkeypatch.setattr(llm_agent, "diagnose_failure", stub_diagnose)

    synthetic = PaymentFailureRecord(
        payment_id="pay_synthetic_unmapped", amount=450000, method="card",
        merchant_id="m", customer_name="C", customer_phone="+919999999999",
        error_reason="payment_failed", error_description="d",
        recovery_state="INGESTED", source="synthetic",
    )
    db_session.add(synthetic)
    db_session.commit()

    await classify(db_session, synthetic)

    assert HELD not in actions(db_session, "pay_synthetic_unmapped")


# --- 12. Malformed payload -------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_payment_failed_returns_400_and_writes_nothing(db_session, monkeypatch):
    from fastapi import HTTPException

    from app.routes import webhooks

    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(webhooks, "DEMO_MODE", True)
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", "XXXXXXXXXXXXXXXXXXXXXX")

    payload = {"event": "payment.failed",
               "payload": {"payment": {"entity": {"amount": 100}}}}  # no id

    class FakeRequest:
        async def body(self):
            return json.dumps(payload).encode()

        async def json(self):
            return payload

        headers = {}

    class FakeBackgroundTasks:
        def add_task(self, *a, **kw):
            raise AssertionError("a malformed payload must schedule no work")

    with pytest.raises(HTTPException) as excinfo:
        await webhooks.receive_webhook(FakeRequest(), FakeBackgroundTasks())

    assert excinfo.value.status_code == 400
    assert db_session.query(PaymentFailureRecord).count() == 0
    assert db_session.query(AuditTrailEntry).count() == 0
