"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import json

import pytest

from app import classifier, llm_agent, llm_cache
from app.models import AuditTrailEntry
from app.schemas import FailureClass


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    path = tmp_path / "llm_cache.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(llm_cache, "CACHE_PATH", str(path))
    monkeypatch.setattr(llm_cache, "DEMO_MODE", True)
    llm_cache._STORE = {}
    llm_cache.reset_stats()

    def record(record_obj, payload, latency_ms=402):
        inputs = llm_agent.diagnosis_inputs(record_obj)
        key = llm_cache.cache_key(
            llm_agent.MODEL_DIAGNOSIS, llm_agent.PROMPT_VERSION_DIAGNOSIS, inputs,
        )
        llm_cache._STORE[key] = {
            "model": llm_agent.MODEL_DIAGNOSIS,
            "text": json.dumps(payload),
            "input_tokens": 180, "output_tokens": 64,
            "latency_ms": latency_ms,
            "recorded_at": "2026-08-25T00:00:00Z", "inputs": inputs,
        }
    return record


@pytest.mark.asyncio
async def test_unmapped_error_is_diagnosed_by_the_model(db_session, payment_record, recorded):
    record = payment_record(
        payment_id="pay_diag_001",
        error_reason="npci_mandate_presentation_declined",
        error_description="Mandate presented on 5th; payer account had insufficient balance at presentation.",
    )
    db_session.add(record)
    db_session.commit()

    recorded(record, {
        "root_cause_class": "MANDATE_BALANCE",
        "technical_explanation": "The e-mandate debit was presented but the payer account lacked balance.",
        "suggested_action": "Re-present after the customer's salary credit date.",
        "confidence": 0.88,
    })

    result = await classifier.classify(db_session, record)

    assert result == FailureClass.MANDATE_BALANCE
    entry = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "FAILURE_DIAGNOSED_LLM"
    ).one()
    assert entry.actor == "llm_agent"
    assert entry.llm_model == "gemini-2.0-flash"
    assert entry.llm_confidence_bp == 8800
    assert "salary credit date" in entry.details


@pytest.mark.asyncio
async def test_out_of_enum_class_escalates_rather_than_raising(db_session, payment_record, recorded):
    record = payment_record(
        payment_id="pay_diag_002",
        error_reason="mystery_error",
        error_description="Something the model has never seen.",
    )
    db_session.add(record)
    db_session.commit()

    recorded(record, {
        "root_cause_class": "COSMIC_RAY",
        "technical_explanation": "Unknown.",
        "suggested_action": "Investigate.",
        "confidence": 0.95,
    })

    result = await classifier.classify(db_session, record)

    assert result == FailureClass.HARD_DECLINE
    actions = [e.action for e in db_session.query(AuditTrailEntry).all()]
    assert "ESCALATED_TO_HUMAN" in actions


@pytest.mark.asyncio
async def test_low_confidence_escalates(db_session, payment_record, recorded):
    record = payment_record(
        payment_id="pay_diag_003",
        error_reason="ambiguous_error",
        error_description="Payment did not go through.",
    )
    db_session.add(record)
    db_session.commit()

    recorded(record, {
        "root_cause_class": "AUTH_FRICTION",
        "technical_explanation": "Possibly an OTP timeout.",
        "suggested_action": "Resend the link.",
        "confidence": 0.41,
    })

    result = await classifier.classify(db_session, record)

    assert result == FailureClass.HARD_DECLINE
    entry = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "ESCALATED_TO_HUMAN"
    ).one()
    assert entry.llm_confidence_bp == 4100


@pytest.mark.asyncio
async def test_suggested_action_is_recorded_but_never_acted_on(db_session, payment_record, recorded):
    """The model's suggestion is evidence, not an instruction."""
    record = payment_record(
        payment_id="pay_diag_005",
        error_reason="issuer_soft_decline",
        error_description="Issuer soft-declined; retry permitted.",
    )
    db_session.add(record)
    db_session.commit()

    recorded(record, {
        "root_cause_class": "TRANSIENT_TECHNICAL",
        "technical_explanation": "Issuer returned a soft decline.",
        "suggested_action": "Call the customer immediately on their mobile.",
        "confidence": 0.91,
    })

    await classifier.classify(db_session, record)

    # The channel comes from the config map for the class, not from the model.
    assert record.recovery_channel == "silent_retry"
    entry = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "FAILURE_DIAGNOSED_LLM"
    ).one()
    assert "not executed" in entry.details
    assert "Call the customer immediately" in entry.details


@pytest.mark.asyncio
async def test_mapped_error_never_calls_the_model(db_session, payment_record, recorded):
    record = payment_record(payment_id="pay_diag_004", error_reason="incorrect_otp")
    db_session.add(record)
    db_session.commit()

    result = await classifier.classify(db_session, record)

    assert result == FailureClass.AUTH_FRICTION
    assert llm_cache.stats() == {"hits": 0, "misses": 0, "writes": 0}


@pytest.mark.asyncio
async def test_cache_miss_does_not_silently_reclassify(db_session, payment_record, recorded):
    """An unavailable model must escalate, never invent a class."""
    record = payment_record(
        payment_id="pay_diag_006",
        error_reason="never_recorded_error",
        error_description="No recorded diagnosis exists for this.",
    )
    db_session.add(record)
    db_session.commit()

    result = await classifier.classify(db_session, record)

    assert result == FailureClass.HARD_DECLINE
    entry = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "ESCALATED_TO_HUMAN"
    ).one()
    assert entry.actor == "system"
    assert "CacheMiss" in entry.details


def test_map_intent_to_class_is_gone():
    """It only ever existed to serve the reply/error miswiring."""
    assert not hasattr(classifier, "map_intent_to_class")
