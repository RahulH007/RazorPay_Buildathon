"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest

from app.models import AuditTrailEntry
from app.recovery_actions import execute_recovery
from app.voice_pipeline import handle_dtmf_response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_class", "expected_action"),
    [
        ("TRANSIENT_TECHNICAL", "RETRY_SILENT_ATTEMPT"),
        ("AUTH_FRICTION", "WHATSAPP_LINK_SENT"),
        ("MANDATE_BALANCE", "MANDATE_RESEQUENCED"),
        # B2B escalates whatsapp -> voice -> human, so step one is WhatsApp
        ("B2B_RECEIVABLE", "WHATSAPP_LINK_SENT"),
    ],
)
async def test_action_dispatch_moves_record_to_intervening(
    db_session, payment_record, failure_class, expected_action
):
    record = payment_record(
        failure_class=failure_class,
        recovery_state="DIAGNOSED",
        error_reason="invoice_overdue_15d" if failure_class == "B2B_RECEIVABLE" else "bank_technical_error",
    )
    db_session.add(record)
    db_session.commit()

    result = await execute_recovery(db_session, record)

    actions = [
        entry.action
        for entry in db_session.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == record.payment_id)
        .all()
    ]
    assert record.recovery_state == "INTERVENING"
    assert result["action"] in {"silent_retry", "whatsapp_link", "mandate_resequence", "voice_recovery"}
    assert expected_action in actions


@pytest.mark.asyncio
async def test_hard_decline_is_blocked_by_fraud_guard(db_session, payment_record):
    record = payment_record(
        failure_class="HARD_DECLINE",
        recovery_state="DIAGNOSED",
        error_reason="compliance_violation",
    )
    db_session.add(record)
    db_session.commit()

    result = await execute_recovery(db_session, record)

    assert result["action"] == "declined"
    assert result["reason_code"] == "HARD_DECLINE"
    assert "zero customer outreach" in result["reason"].lower()
    assert record.recovery_state == "FAILED_STOPPED"

    # The refusal must be on the ledger, not merely returned to the caller.
    actions = [
        e.action
        for e in db_session.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == record.payment_id)
        .all()
    ]
    assert "POLICY_DECLINED_HARD_DECLINE" in actions


@pytest.mark.asyncio
async def test_voice_dtmf_opt_out_stops_active_record(db_session, payment_record):
    record = payment_record(
        failure_class="B2B_RECEIVABLE",
        recovery_state="INTERVENING",
        recovery_channel="hinglish_voice",
    )
    db_session.add(record)
    db_session.commit()

    result = await handle_dtmf_response(db_session, record, "9")

    assert result["response"] == "opt_out"
    assert record.recovery_state == "FAILED_STOPPED"


@pytest.mark.asyncio
async def test_rejected_copy_is_ledgered_and_the_template_is_sent(
    db_session, payment_record, monkeypatch,
):
    """The guard is only worth having if a reviewer can see it fire."""
    from app import llm_agent, recovery_actions
    from app.models import AuditTrailEntry

    record = payment_record(
        payment_id="pay_reject_001", amount=249900, failure_class="AUTH_FRICTION",
    )
    db_session.add(record)
    db_session.commit()

    async def hallucinating_model(rec, link_url):
        text = f"Namaste, aapka ₹9,999.00 ka payment pending hai. {link_url}"
        ok, reason = llm_agent.verify_numbers(text, rec, link_url)
        assert ok is False
        return llm_agent._template_whatsapp(rec, link_url), {
            "model": "gemini-3.6-flash", "input_tokens": 80,
            "output_tokens": 25, "latency_ms": 210,
        }, reason

    monkeypatch.setattr(
        recovery_actions, "generate_whatsapp_message", hallucinating_model,
    )

    result = await recovery_actions.send_whatsapp_link(db_session, record)

    assert "9,999.00" not in result["message"]
    assert "2,499.00" in result["message"]
    entry = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "LLM_OUTPUT_REJECTED"
    ).one()
    assert entry.llm_model == "gemini-3.6-flash"
    assert "249900" in entry.details


@pytest.mark.asyncio
async def test_fraud_quarantine_is_recorded_as_a_system_action(db_session, payment_record):
    """
    A fraud halt must not be logged as a customer opt-out.

    The dashboard drill used to call the opt-out endpoint, which writes
    CUSTOMER_OPT_OUT with actor="customer". Misattributing the actor in a
    ledger built to prove who did what is the one defect that discredits the
    rest of it.
    """
    from app.consent import is_suppressed
    from app.models import AuditTrailEntry
    from app.routes.recovery import quarantine_record

    record = payment_record(
        payment_id="pay_fraud_001",
        customer_phone="+919876512345",
        failure_class="AUTH_FRICTION",
        recovery_state="INTERVENING",
    )
    db_session.add(record)
    db_session.commit()

    import app.routes.recovery as recovery_routes
    original = recovery_routes.SessionLocal
    recovery_routes.SessionLocal = lambda: db_session
    try:
        result = await quarantine_record("pay_fraud_001")
    finally:
        recovery_routes.SessionLocal = original

    assert result["status"] == "quarantined"
    assert record.recovery_state == "FAILED_STOPPED"

    entry = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "FRAUD_QUARANTINE"
    ).one()
    assert entry.actor == "system"

    actions = [e.action for e in db_session.query(AuditTrailEntry).all()]
    assert "CUSTOMER_OPT_OUT" not in actions

    # A fraud suspicion is ours, not the customer's: their other payments
    # must not be suppressed by it.
    blocked, _reason = is_suppressed(db_session, "+919876512345", "whatsapp")
    assert blocked is False
