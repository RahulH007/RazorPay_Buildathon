"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import json

import pytest

from app import inbound, llm_agent, llm_cache
from app.consent import is_suppressed
from app.models import AuditTrailEntry


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    path = tmp_path / "llm_cache.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(llm_cache, "CACHE_PATH", str(path))
    monkeypatch.setattr(llm_cache, "DEMO_MODE", True)
    llm_cache._STORE = {}
    llm_cache.reset_stats()

    def record(record_obj, message, payload):
        inputs = llm_agent.reply_inputs(record_obj, message)
        key = llm_cache.cache_key(
            llm_agent.MODEL_REPLY, llm_agent.PROMPT_VERSION_REPLY, inputs,
        )
        llm_cache._STORE[key] = {
            "model": llm_agent.MODEL_REPLY, "text": json.dumps(payload),
            "input_tokens": 90, "output_tokens": 30, "latency_ms": 288,
            "recorded_at": "2026-08-25T00:00:00Z", "inputs": inputs,
        }
    return record


@pytest.mark.asyncio
async def test_opt_out_suppresses_the_contact_across_payments(db_session, payment_record, recorded):
    record = payment_record(payment_id="pay_in_001", customer_phone="+919876500011")
    db_session.add(record)
    db_session.commit()
    message = "mujhe ye messages nahi chahiye"
    recorded(record, message, {
        "intent": "opt_out", "confidence": 0.96, "extracted_date": None,
        "sentiment": "negative", "requires_human": False,
        "reasoning": "Customer asked to stop receiving messages",
    })

    result = await inbound.handle_reply(db_session, record, message)

    assert result["intent"] == "opt_out"
    assert result["action_taken"] == "suppressed"
    blocked, _reason = is_suppressed(db_session, "+919876500011", "whatsapp")
    assert blocked is True


@pytest.mark.asyncio
async def test_regex_overrides_a_wrong_model_verdict(db_session, payment_record, recorded):
    """The model can only ADD suppression, never remove it."""
    record = payment_record(payment_id="pay_in_002", customer_phone="+919876500022")
    db_session.add(record)
    db_session.commit()
    message = "band karo ye sab"
    recorded(record, message, {
        "intent": "will_pay", "confidence": 0.93, "extracted_date": None,
        "sentiment": "positive", "requires_human": False,
        "reasoning": "Customer agreed to pay",
    })

    result = await inbound.handle_reply(db_session, record, message)

    assert result["regex_opt_out"] is True
    assert result["action_taken"] == "suppressed"
    blocked, _reason = is_suppressed(db_session, "+919876500022", "whatsapp")
    assert blocked is True


@pytest.mark.asyncio
async def test_delay_sets_promise_to_pay(db_session, payment_record, recorded):
    record = payment_record(payment_id="pay_in_003", customer_phone="+919876500033")
    db_session.add(record)
    db_session.commit()
    message = "salary aane do, 1st ko kar dunga"
    recorded(record, message, {
        "intent": "request_delay", "confidence": 0.9,
        "extracted_date": "2026-09-01", "sentiment": "neutral",
        "requires_human": False, "reasoning": "Customer will pay on the 1st",
    })

    await inbound.handle_reply(db_session, record, message)

    assert record.promise_to_pay_at is not None
    assert record.promise_to_pay_at.date().isoformat() == "2026-09-01"
    actions = [e.action for e in db_session.query(AuditTrailEntry).all()]
    assert "PROMISE_TO_PAY_RECORDED" in actions


@pytest.mark.asyncio
async def test_will_pay_defers_24h_using_the_same_mechanism(db_session, payment_record, recorded):
    record = payment_record(payment_id="pay_in_004", customer_phone="+919876500044")
    db_session.add(record)
    db_session.commit()
    message = "abhi karta hoon"
    recorded(record, message, {
        "intent": "will_pay", "confidence": 0.92, "extracted_date": None,
        "sentiment": "positive", "requires_human": False,
        "reasoning": "Customer agreed to pay now",
    })

    await inbound.handle_reply(db_session, record, message)

    assert record.promise_to_pay_at is not None


@pytest.mark.asyncio
async def test_low_confidence_escalates(db_session, payment_record, recorded):
    record = payment_record(payment_id="pay_in_005", customer_phone="+919876500055")
    db_session.add(record)
    db_session.commit()
    message = "hmm"
    recorded(record, message, {
        "intent": "unclear", "confidence": 0.22, "extracted_date": None,
        "sentiment": "neutral", "requires_human": True,
        "reasoning": "No clear intent",
    })

    result = await inbound.handle_reply(db_session, record, message)

    assert result["action_taken"] == "escalated_to_human"
    actions = [e.action for e in db_session.query(AuditTrailEntry).all()]
    assert "ESCALATED_TO_HUMAN" in actions


@pytest.mark.asyncio
async def test_every_reply_is_ledgered_with_model_metadata(db_session, payment_record, recorded):
    record = payment_record(payment_id="pay_in_006", customer_phone="+919876500066")
    db_session.add(record)
    db_session.commit()
    message = "kal kar dunga"
    recorded(record, message, {
        "intent": "request_delay", "confidence": 0.87,
        "extracted_date": "2026-08-26", "sentiment": "neutral",
        "requires_human": False, "reasoning": "Tomorrow",
    })

    await inbound.handle_reply(db_session, record, message)

    entry = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "CUSTOMER_REPLY_PARSED"
    ).one()
    assert entry.actor == "llm_agent"
    assert entry.llm_model == "gemini-2.0-flash"
    assert entry.llm_confidence_bp == 8700
    assert entry.llm_latency_ms == 288


@pytest.mark.asyncio
async def test_dispute_goes_to_the_human_queue(db_session, payment_record, recorded):
    record = payment_record(
        payment_id="pay_in_007", customer_phone="+919876500077",
        failure_class="B2B_RECEIVABLE", recovery_state="INTERVENING",
    )
    db_session.add(record)
    db_session.commit()
    message = "amount galat hai, invoice check karo"
    recorded(record, message, {
        "intent": "dispute", "confidence": 0.94, "extracted_date": None,
        "sentiment": "negative", "requires_human": True,
        "reasoning": "Customer disputes the amount",
    })

    result = await inbound.handle_reply(db_session, record, message)

    assert result["action_taken"] == "human_queue"
