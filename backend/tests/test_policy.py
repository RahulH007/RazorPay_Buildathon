"""
Policy engine tests.

Each reason code gets a test that proves it fires for the reason it claims,
rather than merely that something stopped. The original guardrails passed
their unit tests too — what they lacked was any path from those functions to a
decision that actually halted work.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app import policy
from app.config import IST, MAX_RETRIES
from app.consent import record_opt_out
from app.models import AuditTrailEntry
from app.policy import ReasonCode, decide_next_action
from app.recovery_actions import execute_recovery
from app.state_machine import log_audit


def _diagnosed(payment_record, **overrides):
    defaults = {"recovery_state": "DIAGNOSED", "batch_id": "batch_test"}
    return payment_record(**{**defaults, **overrides})


# --- Proceed ----------------------------------------------------------------


def test_first_attempt_proceeds_on_the_cheapest_rung(db_session, payment_record):
    record = _diagnosed(payment_record, failure_class="B2B_RECEIVABLE", amount=5000000)
    db_session.add(record)
    db_session.commit()

    decision = decide_next_action(db_session, record)

    assert decision.should_act is True
    assert decision.reason_code == ReasonCode.PROCEED
    # WhatsApp before voice: the ladder escalates in cost, never the reverse.
    assert decision.channel == "whatsapp_link"
    assert decision.attempt_number == 0


def test_ladder_escalates_whatsapp_then_voice_then_human(db_session, payment_record):
    record = _diagnosed(payment_record, failure_class="B2B_RECEIVABLE", amount=5000000)
    db_session.add(record)
    db_session.commit()

    seen = []
    for action in ("WHATSAPP_LINK_SENT", "VOICE_CALL_INITIATED"):
        seen.append(decide_next_action(db_session, record).channel)
        log_audit(db_session, record, action=action)
    seen.append(decide_next_action(db_session, record).channel)

    assert seen == ["whatsapp_link", "hinglish_voice", "human_queue"]


# --- Stopping rules ---------------------------------------------------------


def test_hard_decline_never_acts(db_session, payment_record):
    record = _diagnosed(
        payment_record, failure_class="HARD_DECLINE", error_reason="compliance_violation"
    )
    db_session.add(record)
    db_session.commit()

    decision = decide_next_action(db_session, record)

    assert decision.should_act is False
    assert decision.reason_code == ReasonCode.HARD_DECLINE
    assert decision.channel is None


def test_retry_cap_stops_a_free_channel(db_session, payment_record):
    """
    Silent retry costs nothing and never reaches the customer, so no cost or
    consent rule constrains it. MAX_RETRIES is the only thing that does — which
    is why the transient ladder is deliberately longer than the cap.
    """
    record = _diagnosed(
        payment_record, failure_class="TRANSIENT_TECHNICAL", amount=5000000
    )
    db_session.add(record)
    db_session.commit()

    assert len(policy.ATTEMPT_LADDER["TRANSIENT_TECHNICAL"]) > MAX_RETRIES

    for _ in range(MAX_RETRIES):
        assert decide_next_action(db_session, record).should_act is True
        log_audit(db_session, record, action="RETRY_SILENT_ATTEMPT")

    decision = decide_next_action(db_session, record)
    assert decision.should_act is False
    assert decision.reason_code == ReasonCode.RETRY_CAP_REACHED
    assert str(MAX_RETRIES) in decision.reason


def test_ladder_exhausts_before_the_cap_for_short_ladders(db_session, payment_record):
    record = _diagnosed(payment_record, failure_class="AUTH_FRICTION", amount=5000000)
    db_session.add(record)
    db_session.commit()

    for _ in range(len(policy.ATTEMPT_LADDER["AUTH_FRICTION"])):
        log_audit(db_session, record, action="WHATSAPP_LINK_SENT")

    decision = decide_next_action(db_session, record)
    assert decision.reason_code == ReasonCode.LADDER_EXHAUSTED


def test_cac_ceiling_blocks_the_second_attempt_on_a_tiny_payment(
    db_session, payment_record
):
    """Rs 6.50: one 50p message fits under the 97p ceiling, two do not."""
    record = _diagnosed(payment_record, failure_class="AUTH_FRICTION", amount=650)
    db_session.add(record)
    db_session.commit()

    first = decide_next_action(db_session, record)
    assert first.should_act is True

    log_audit(db_session, record, action="WHATSAPP_LINK_SENT", cost_paise=50)

    second = decide_next_action(db_session, record)
    assert second.should_act is False
    assert second.reason_code == ReasonCode.CAC_CEILING
    assert "ceiling" in second.reason.lower()


def test_negative_expected_value_blocks_the_first_attempt(db_session, payment_record):
    """Rs 5.00 at 40% success and 20% margin is 40p of value for a 50p message."""
    record = _diagnosed(payment_record, failure_class="AUTH_FRICTION", amount=500)
    db_session.add(record)
    db_session.commit()

    decision = decide_next_action(db_session, record)

    assert decision.should_act is False
    assert decision.reason_code == ReasonCode.NEGATIVE_EXPECTED_VALUE
    assert "destroys value" in decision.reason


def test_consent_withdrawal_blocks_a_different_payment(db_session, payment_record):
    phone = "+919812340004"
    record = _diagnosed(
        payment_record, failure_class="AUTH_FRICTION", amount=5000000,
        customer_phone=phone, payment_id="pay_later",
    )
    db_session.add(record)
    db_session.commit()

    assert decide_next_action(db_session, record).should_act is True

    record_opt_out(db_session, phone, "dtmf_9", "pay_earlier")

    decision = decide_next_action(db_session, record)
    assert decision.should_act is False
    assert decision.reason_code == ReasonCode.CONSENT_WITHDRAWN


def test_quiet_hours_defer_voice_only(db_session, payment_record):
    record = _diagnosed(payment_record, failure_class="B2B_RECEIVABLE", amount=5000000)
    db_session.add(record)
    db_session.commit()

    midnight = datetime(2026, 8, 25, 23, 30, tzinfo=IST)

    # Rung one is WhatsApp, which is not time-restricted.
    assert decide_next_action(db_session, record, now=midnight).should_act is True

    log_audit(db_session, record, action="WHATSAPP_LINK_SENT", cost_paise=50)

    # Rung two is voice, which is.
    decision = decide_next_action(db_session, record, now=midnight)
    assert decision.should_act is False
    assert decision.reason_code == ReasonCode.QUIET_HOURS_DEFERRED


def test_holdout_is_never_contacted(db_session, payment_record):
    record = _diagnosed(payment_record, failure_class="AUTH_FRICTION", amount=5000000)
    db_session.add(record)
    db_session.commit()

    decision = decide_next_action(db_session, record, is_holdout=True)

    assert decision.should_act is False
    assert decision.reason_code == ReasonCode.HOLDOUT_CONTROL


# --- Refusals are ledgered --------------------------------------------------


@pytest.mark.asyncio
async def test_every_refusal_writes_a_why_we_didnt_act_entry(
    db_session, payment_record
):
    record = _diagnosed(payment_record, failure_class="AUTH_FRICTION", amount=500)
    db_session.add(record)
    db_session.commit()

    result = await execute_recovery(db_session, record)

    assert result["action"] == "declined"

    entry = (
        db_session.query(AuditTrailEntry)
        .filter(AuditTrailEntry.action.like("POLICY_DECLINED_%"))
        .one()
    )
    assert entry.actor == "policy_engine"
    assert entry.details.startswith("WHY_WE_DIDNT_ACT:")
    assert entry.cost_paise == 0


@pytest.mark.asyncio
async def test_quiet_hours_defers_without_closing_the_record(
    db_session, payment_record
):
    """
    A deferral is not a stop. The record must stay open so the call can be
    placed when the window opens, unlike every other refusal.
    """
    record = _diagnosed(payment_record, failure_class="B2B_RECEIVABLE", amount=5000000)
    db_session.add(record)
    db_session.commit()
    log_audit(db_session, record, action="WHATSAPP_LINK_SENT", cost_paise=50)

    midnight = datetime(2026, 8, 25, 23, 30, tzinfo=IST)
    result = await execute_recovery(db_session, record, now=midnight)

    assert result["reason_code"] == ReasonCode.QUIET_HOURS_DEFERRED
    assert record.recovery_state != "FAILED_STOPPED"


@pytest.mark.asyncio
async def test_terminal_refusal_closes_the_record(db_session, payment_record):
    record = _diagnosed(payment_record, failure_class="AUTH_FRICTION", amount=500)
    db_session.add(record)
    db_session.commit()

    await execute_recovery(db_session, record)

    assert record.recovery_state == "FAILED_STOPPED"


# --- Promise-to-pay deferral ---

def test_future_promise_defers_the_next_attempt(db_session, payment_record):
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    record = payment_record(
        payment_id="pay_p2p_001",
        failure_class="AUTH_FRICTION",
        recovery_state="INTERVENING",
        promise_to_pay_at=now + timedelta(days=2),
    )
    db_session.add(record)
    db_session.commit()

    decision = decide_next_action(db_session, record, now=now)

    assert decision.should_act is False
    assert decision.reason_code == ReasonCode.PROMISE_TO_PAY_PENDING


def test_elapsed_promise_does_not_block(db_session, payment_record):
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    record = payment_record(
        payment_id="pay_p2p_002",
        failure_class="AUTH_FRICTION",
        recovery_state="INTERVENING",
        promise_to_pay_at=now - timedelta(hours=1),
    )
    db_session.add(record)
    db_session.commit()

    decision = decide_next_action(db_session, record, now=now)

    assert decision.should_act is True


def test_promise_does_not_override_hard_decline(db_session, payment_record):
    """The first refusal must be the most fundamental one."""
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    record = payment_record(
        payment_id="pay_p2p_003",
        failure_class="HARD_DECLINE",
        promise_to_pay_at=now + timedelta(days=2),
    )
    db_session.add(record)
    db_session.commit()

    decision = decide_next_action(db_session, record, now=now)

    assert decision.reason_code == ReasonCode.HARD_DECLINE


def test_naive_promise_datetime_is_treated_as_utc(db_session, payment_record):
    """SQLite returns naive datetimes; comparing them to an aware now raises."""
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    record = payment_record(
        payment_id="pay_p2p_004",
        failure_class="AUTH_FRICTION",
        recovery_state="INTERVENING",
        promise_to_pay_at=datetime(2026, 8, 27, 12, 0),
    )
    db_session.add(record)
    db_session.commit()

    decision = decide_next_action(db_session, record, now=now)

    assert decision.reason_code == ReasonCode.PROMISE_TO_PAY_PENDING
